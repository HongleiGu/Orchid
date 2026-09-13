/**
 * Server-sent events over fetch.
 *
 * Not `EventSource`, deliberately: EventSource cannot send request headers,
 * and the backend authenticates only through headers — it refuses tokens in the
 * query string so they never land in access logs. A browser EventSource client
 * would therefore have to weaken the server. Reading the body as a stream costs
 * a small parser and buys header auth, abort, and control over reconnection.
 *
 * Needs `fetch` with a streaming `ReadableStream` body: browsers and Tauri
 * webviews have it; React Native's fetch does not, so a native client would
 * need a different transport behind the same `openRunStream` contract.
 */
import { errorForStatus, NetworkError, type OrchidError } from "./errors";
import type { RunEvent } from "./types";

export interface SseMessage {
  id: string | null;
  event: string | null;
  data: string;
}

/**
 * Incremental SSE parser. Chunks from the network split anywhere — mid-line,
 * mid-UTF-8 sequence, between \r and \n — so state carries across `push` calls.
 */
export class SseParser {
  private buffer = "";
  private data: string[] = [];
  private id: string | null = null;
  private event: string | null = null;
  private pendingCR = false;
  private readonly decoder = new TextDecoder();

  constructor(
    private readonly onMessage: (message: SseMessage) => void,
    private readonly onComment: (comment: string) => void = () => {},
  ) {}

  push(chunk: Uint8Array | string): void {
    let text = typeof chunk === "string" ? chunk : this.decoder.decode(chunk, { stream: true });
    // A \r at the end of the previous chunk may pair with a \n starting this one.
    if (this.pendingCR && text.startsWith("\n")) text = text.slice(1);
    this.pendingCR = text.endsWith("\r");
    this.buffer += text;

    let lineEnd: number;
    while ((lineEnd = this.nextLineBreak()) !== -1) {
      const line = this.buffer.slice(0, lineEnd);
      const breakLen = this.buffer[lineEnd] === "\r" && this.buffer[lineEnd + 1] === "\n" ? 2 : 1;
      this.buffer = this.buffer.slice(lineEnd + breakLen);
      this.handleLine(line);
    }
  }

  private nextLineBreak(): number {
    for (let i = 0; i < this.buffer.length; i++) {
      const ch = this.buffer[i];
      if (ch === "\n") return i;
      if (ch === "\r") {
        // A lone trailing \r may be the first half of \r\n; wait for more.
        if (i === this.buffer.length - 1) return -1;
        return i;
      }
    }
    return -1;
  }

  private handleLine(line: string): void {
    if (line === "") {
      this.dispatch();
      return;
    }
    if (line.startsWith(":")) {
      this.onComment(line.slice(1).trimStart());
      return;
    }
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);

    switch (field) {
      case "data":
        this.data.push(value);
        break;
      case "id":
        if (!value.includes("\0")) this.id = value;
        break;
      case "event":
        this.event = value;
        break;
      default:
        // "retry" and unknown fields: reconnection timing is owned by
        // openRunStream, not dictated by the server.
        break;
    }
  }

  private dispatch(): void {
    if (this.data.length === 0) {
      this.event = null;
      return;
    }
    this.onMessage({ id: this.id, event: this.event, data: this.data.join("\n") });
    this.data = [];
    this.event = null;
  }
}

// ── Resumable run stream ─────────────────────────────────────────────────────

export type StreamState = "connecting" | "open" | "reconnecting" | "ended" | "failed";

export interface RunStreamOptions {
  baseUrl: string;
  apiKey: string;
  runId: string;
  verbosity?: string;
  /** Resume after this sequence number (e.g. the last event already rendered). */
  lastEventId?: number;
  onEvent: (event: RunEvent) => void;
  onState?: (state: StreamState, detail?: OrchidError) => void;
  fetchImpl?: typeof fetch;
  /**
   * Longest silence before the connection is presumed dead and re-opened. The
   * server sends a keepalive every 25s, so anything well beyond that is a
   * connection a mobile network dropped without telling either side.
   */
  idleTimeoutMs?: number;
  /** First reconnect delay; doubles per consecutive failure up to maxBackoffMs. */
  initialBackoffMs?: number;
  maxBackoffMs?: number;
  signal?: AbortSignal;
}

export interface RunStreamHandle {
  close(): void;
  /** Resolves when the run ends, the stream fails permanently, or it is closed. */
  done: Promise<StreamState>;
}

/**
 * The run-level terminal event — mirrors the backend's `_run_has_ended`.
 * A CollabGroup also emits "terminated" (with an agent and a reason) mid-run,
 * so the status key is what marks the run itself as over.
 */
export function isRunEnd(event: Pick<RunEvent, "type" | "payload">): boolean {
  return (
    event.type === "terminated" &&
    typeof event.payload === "object" &&
    event.payload !== null &&
    "status" in event.payload
  );
}

const sleep = (ms: number, signal: AbortSignal) =>
  new Promise<void>((resolve) => {
    if (signal.aborted) return resolve();
    const t = setTimeout(resolve, ms);
    signal.addEventListener("abort", () => {
      clearTimeout(t);
      resolve();
    }, { once: true });
  });

/**
 * Follow a run's events until it ends, reconnecting with Last-Event-ID across
 * dropped connections. Events are delivered at most once each, in order, even
 * if the server or a proxy replays some — the sequence number is the cursor.
 */
export function openRunStream(options: RunStreamOptions): RunStreamHandle {
  const fetchImpl = options.fetchImpl ?? globalThis.fetch.bind(globalThis);
  const idleTimeoutMs = options.idleTimeoutMs ?? 70_000;
  const initialBackoffMs = options.initialBackoffMs ?? 1_000;
  const maxBackoffMs = options.maxBackoffMs ?? 15_000;
  const lifetime = new AbortController();
  options.signal?.addEventListener("abort", () => lifetime.abort(), { once: true });

  let lastSeq = options.lastEventId ?? 0;
  const setState = (s: StreamState, detail?: OrchidError) => options.onState?.(s, detail);

  const done = (async (): Promise<StreamState> => {
    let attempt = 0;
    while (!lifetime.signal.aborted) {
      setState(attempt === 0 ? "connecting" : "reconnecting");
      const connection = new AbortController();
      const abortConnection = () => connection.abort();
      lifetime.signal.addEventListener("abort", abortConnection, { once: true });

      let idleTimer: ReturnType<typeof setTimeout> | undefined;
      const armIdle = () => {
        clearTimeout(idleTimer);
        idleTimer = setTimeout(() => connection.abort(), idleTimeoutMs);
      };

      let ended = false;
      try {
        const params = new URLSearchParams();
        if (options.verbosity) params.set("verbosity", options.verbosity);
        const qs = params.toString();
        const url = `${options.baseUrl.replace(/\/+$/, "")}/api/v1/runs/${encodeURIComponent(options.runId)}/stream${qs ? `?${qs}` : ""}`;

        const headers: Record<string, string> = {
          Accept: "text/event-stream",
          Authorization: `Bearer ${options.apiKey}`,
        };
        if (lastSeq > 0) headers["Last-Event-ID"] = String(lastSeq);

        armIdle();
        const response = await fetchImpl(url, { headers, signal: connection.signal, cache: "no-store" });

        if (!response.ok) {
          const text = await response.text().catch(() => "");
          let message = `Stream refused (${response.status})`;
          try {
            message = JSON.parse(text)?.error?.message ?? message;
          } catch { /* not JSON — e.g. an nginx 502 page */ }
          const error = errorForStatus(response.status, message, null);
          // Retrying cannot fix a wrong key, a forbidden run or a missing one.
          if ([401, 403, 404].includes(response.status)) {
            setState("failed", error);
            return "failed";
          }
          throw error;
        }
        if (!response.body) throw new NetworkError("Response has no readable body");

        attempt = 0;
        setState("open");
        const reader = response.body.getReader();
        const parser = new SseParser((message) => {
          let event: RunEvent;
          try {
            event = JSON.parse(message.data) as RunEvent;
          } catch {
            return;
          }
          const seq = typeof event.seq === "number" ? event.seq : Number(message.id);
          if (Number.isFinite(seq)) {
            if (seq <= lastSeq) return;
            lastSeq = seq;
          }
          options.onEvent(event);
          if (isRunEnd(event)) ended = true;
        });

        while (true) {
          const { value, done: finished } = await reader.read();
          if (finished) break;
          armIdle();
          if (value) parser.push(value);
          if (ended) {
            await reader.cancel().catch(() => {});
            break;
          }
        }
      } catch (error) {
        if (lifetime.signal.aborted) break;
        const detail = error instanceof Error && "status" in error
          ? (error as OrchidError)
          : new NetworkError(error instanceof Error ? error.message : String(error), error);
        setState("reconnecting", detail);
      } finally {
        clearTimeout(idleTimer);
        lifetime.signal.removeEventListener("abort", abortConnection);
      }

      if (ended) {
        setState("ended");
        return "ended";
      }
      if (lifetime.signal.aborted) break;

      // The server closes the stream only when the run ends, so a close without
      // a terminal event means a proxy or network cut it: resume where we were.
      attempt += 1;
      const backoff = Math.min(maxBackoffMs, initialBackoffMs * 2 ** Math.min(attempt - 1, 4));
      // Jitter, so many clients dropped by one server restart do not all
      // reconnect in the same instant.
      const jitter = Math.floor(Math.random() * Math.min(300, initialBackoffMs));
      await sleep(backoff + jitter, lifetime.signal);
    }
    setState("ended");
    return "ended";
  })();

  return { close: () => lifetime.abort(), done };
}
