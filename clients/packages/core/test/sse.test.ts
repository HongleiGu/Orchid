import { describe, expect, it } from "vitest";

import { AuthError } from "../src/errors";
import { isRunEnd, openRunStream, SseParser, type SseMessage, type StreamState } from "../src/sse";
import type { RunEvent } from "../src/types";

const enc = new TextEncoder();

function collect() {
  const messages: SseMessage[] = [];
  const comments: string[] = [];
  const parser = new SseParser((m) => messages.push(m), (c) => comments.push(c));
  return { parser, messages, comments };
}

// ── parser ───────────────────────────────────────────────────────────────────

describe("SseParser", () => {
  it("dispatches id and data on a blank line", () => {
    const { parser, messages } = collect();
    parser.push("id: 7\ndata: {\"seq\":7}\n\n");
    expect(messages).toEqual([{ id: "7", event: null, data: "{\"seq\":7}" }]);
  });

  it("survives a chunk boundary anywhere, including inside a line", () => {
    const whole = "id: 1\ndata: hello\n\nid: 2\ndata: world\n\n";
    for (let cut = 1; cut < whole.length; cut++) {
      const { parser, messages } = collect();
      parser.push(whole.slice(0, cut));
      parser.push(whole.slice(cut));
      expect(messages.map((m) => m.data), `cut at ${cut}`).toEqual(["hello", "world"]);
    }
  });

  it("handles CRLF line endings, including a \\r\\n split across chunks", () => {
    const { parser, messages } = collect();
    parser.push("id: 3\r\ndata: a\r");
    parser.push("\n\r\n");
    expect(messages).toEqual([{ id: "3", event: null, data: "a" }]);
  });

  it("does not split a multi-byte character cut between chunks", () => {
    // Payloads are Chinese; a UTF-8 sequence cut in half must not become U+FFFD.
    const bytes = enc.encode("data: 选股建议\n\n");
    const { parser, messages } = collect();
    parser.push(bytes.slice(0, 8)); // inside "选"
    parser.push(bytes.slice(8));
    expect(messages[0]?.data).toBe("选股建议");
  });

  it("joins multi-line data with newlines", () => {
    const { parser, messages } = collect();
    parser.push("data: line one\ndata: line two\n\n");
    expect(messages[0]?.data).toBe("line one\nline two");
  });

  it("routes keepalive comments aside rather than dispatching them", () => {
    const { parser, messages, comments } = collect();
    parser.push(": keepalive\n\n: keepalive\n\n");
    expect(messages).toEqual([]);
    expect(comments).toEqual(["keepalive", "keepalive"]);
  });

  it("keeps the last id for events that omit one", () => {
    const { parser, messages } = collect();
    parser.push("id: 9\ndata: a\n\ndata: b\n\n");
    expect(messages.map((m) => m.id)).toEqual(["9", "9"]);
  });
});

// ── run end detection ────────────────────────────────────────────────────────

describe("isRunEnd", () => {
  it("recognises the executor's terminal event", () => {
    expect(isRunEnd({ type: "terminated", payload: { status: "done" } })).toBe(true);
  });

  it("ignores a CollabGroup's terminated event, which fires mid-run", () => {
    expect(isRunEnd({ type: "terminated", payload: { reason: "goal met", total_calls: 4 } })).toBe(false);
  });
});

// ── resumable stream ─────────────────────────────────────────────────────────

const frame = (e: Partial<RunEvent> & { seq: number; type: string }) =>
  `id: ${e.seq}\ndata: ${JSON.stringify({ agent: null, payload: {}, ...e })}\n\n`;

const END = frame({ seq: 99, type: "terminated", payload: { status: "done" } });

type Script = { status?: number; body?: string; chunks?: string[]; hang?: boolean };

/** A fetch that serves one scripted response per call, recording each request. */
function scriptedFetch(scripts: Script[]) {
  const calls: { url: string; headers: Record<string, string> }[] = [];
  const impl = (async (url: string, init?: RequestInit) => {
    const headers = (init?.headers ?? {}) as Record<string, string>;
    calls.push({ url, headers });
    const script = scripts[Math.min(calls.length - 1, scripts.length - 1)]!;
    if (script.status && script.status >= 400) {
      return new Response(script.body ?? "", { status: script.status });
    }
    const chunks = script.chunks ?? [];
    const signal = init?.signal;
    const stream = new ReadableStream<Uint8Array>({
      start(controller) {
        for (const c of chunks) controller.enqueue(enc.encode(c));
        if (script.hang) {
          signal?.addEventListener("abort", () => controller.error(new DOMException("aborted", "AbortError")));
          return;
        }
        controller.close();
      },
    });
    return new Response(stream, { status: 200, headers: { "Content-Type": "text/event-stream" } });
  }) as unknown as typeof fetch;
  return { impl, calls };
}

const fast = { initialBackoffMs: 1, maxBackoffMs: 2 };

describe("openRunStream", () => {
  it("delivers events in order and resolves when the run ends", async () => {
    const { impl, calls } = scriptedFetch([{
      chunks: [frame({ seq: 1, type: "agent_start" }), ": keepalive\n\n", frame({ seq: 2, type: "message" }), END],
    }]);
    const seen: number[] = [];
    const handle = openRunStream({ baseUrl: "https://x", apiKey: "k", runId: "r1", onEvent: (e) => seen.push(e.seq), fetchImpl: impl, ...fast });

    expect(await handle.done).toBe("ended");
    expect(seen).toEqual([1, 2, 99]);
    expect(calls).toHaveLength(1);
    expect(calls[0]!.headers.Authorization).toBe("Bearer k");
  });

  it("does not stop on a mid-run CollabGroup terminated event", async () => {
    const { impl } = scriptedFetch([{
      chunks: [frame({ seq: 1, type: "terminated", payload: { reason: "done", total_calls: 3 } }), frame({ seq: 2, type: "message" }), END],
    }]);
    const seen: number[] = [];
    const handle = openRunStream({ baseUrl: "https://x", apiKey: "k", runId: "r1", onEvent: (e) => seen.push(e.seq), fetchImpl: impl, ...fast });
    await handle.done;
    expect(seen).toEqual([1, 2, 99]);
  });

  it("resumes with Last-Event-ID after a dropped connection, without duplicates", async () => {
    const { impl, calls } = scriptedFetch([
      // First connection dies after seq 2 with no terminal event: a cut, not an end.
      { chunks: [frame({ seq: 1, type: "a" }), frame({ seq: 2, type: "b" })] },
      // The server replays from after the cursor, and a proxy re-sends seq 2.
      { chunks: [frame({ seq: 2, type: "b" }), frame({ seq: 3, type: "c" }), END] },
    ]);
    const seen: number[] = [];
    const handle = openRunStream({ baseUrl: "https://x", apiKey: "k", runId: "r1", onEvent: (e) => seen.push(e.seq), fetchImpl: impl, ...fast });

    expect(await handle.done).toBe("ended");
    expect(seen).toEqual([1, 2, 3, 99]);
    expect(calls).toHaveLength(2);
    expect(calls[0]!.headers["Last-Event-ID"]).toBeUndefined();
    expect(calls[1]!.headers["Last-Event-ID"]).toBe("2");
  });

  it("starts from a supplied cursor", async () => {
    const { impl, calls } = scriptedFetch([{ chunks: [END] }]);
    const handle = openRunStream({ baseUrl: "https://x", apiKey: "k", runId: "r1", lastEventId: 40, onEvent: () => {}, fetchImpl: impl, ...fast });
    await handle.done;
    expect(calls[0]!.headers["Last-Event-ID"]).toBe("40");
  });

  it("gives up immediately on 401 instead of retrying a bad key", async () => {
    const { impl, calls } = scriptedFetch([{ status: 401, body: JSON.stringify({ error: { message: "Missing or invalid API key" } }) }]);
    const states: [StreamState, unknown][] = [];
    const handle = openRunStream({
      baseUrl: "https://x", apiKey: "bad", runId: "r1", onEvent: () => {}, fetchImpl: impl,
      onState: (s, d) => states.push([s, d]), ...fast,
    });

    expect(await handle.done).toBe("failed");
    expect(calls).toHaveLength(1);
    const failure = states.find(([s]) => s === "failed")?.[1];
    expect(failure).toBeInstanceOf(AuthError);
    expect((failure as AuthError).message).toBe("Missing or invalid API key");
  });

  it("retries through a gateway error while the backend restarts", async () => {
    const { impl, calls } = scriptedFetch([
      { status: 502, body: "<html>502 Bad Gateway</html>" },
      { status: 502, body: "<html>502 Bad Gateway</html>" },
      { chunks: [frame({ seq: 1, type: "a" }), END] },
    ]);
    const seen: number[] = [];
    const handle = openRunStream({ baseUrl: "https://x", apiKey: "k", runId: "r1", onEvent: (e) => seen.push(e.seq), fetchImpl: impl, ...fast });
    expect(await handle.done).toBe("ended");
    expect(calls).toHaveLength(3);
    expect(seen).toEqual([1, 99]);
  });

  it("re-opens a connection that has gone silent", async () => {
    const { impl, calls } = scriptedFetch([
      { chunks: [frame({ seq: 1, type: "a" })], hang: true },
      { chunks: [END] },
    ]);
    const handle = openRunStream({
      baseUrl: "https://x", apiKey: "k", runId: "r1", onEvent: () => {}, fetchImpl: impl,
      idleTimeoutMs: 30, ...fast,
    });
    expect(await handle.done).toBe("ended");
    expect(calls).toHaveLength(2);
    expect(calls[1]!.headers["Last-Event-ID"]).toBe("1");
  });

  it("close() stops a stream that would otherwise run forever", async () => {
    const { impl } = scriptedFetch([{ chunks: [frame({ seq: 1, type: "a" })], hang: true }]);
    const handle = openRunStream({ baseUrl: "https://x", apiKey: "k", runId: "r1", onEvent: () => {}, fetchImpl: impl, ...fast });
    setTimeout(() => handle.close(), 20);
    await expect(handle.done).resolves.toBe("ended");
  });
});
