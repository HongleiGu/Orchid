import { errorForStatus, NetworkError } from "./errors";
import { openRunStream, type RunStreamHandle, type RunStreamOptions } from "./sse";
import type {
  Attestation,
  DataResponse,
  PageResponse,
  Run,
  RunDetail,
  RunTemplateResult,
  SpanNode,
  Template,
  UsageSummary,
  Verbosity,
} from "./types";

export interface ClientConfig {
  /** Origin of the deployment, e.g. "https://www.dotslash.cn". No trailing path. */
  baseUrl: string;
  /**
   * A per-user issued key. The static operator key also works but carries no
   * identity, so plans and attestations do not apply to it.
   */
  apiKey: string;
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
}

/**
 * Typed access to the parts of the Orchid API a controller needs.
 *
 * Framework-free and storage-free on purpose, so the same code serves the PWA
 * console now and a Tauri shell or the publisher app later — each supplies its
 * own `fetch` and its own credential store.
 */
export class OrchidClient {
  readonly baseUrl: string;
  private readonly apiKey: string;
  private readonly fetchImpl: typeof fetch;
  private readonly timeoutMs: number;

  constructor(config: ClientConfig) {
    this.baseUrl = config.baseUrl.replace(/\/+$/, "");
    this.apiKey = config.apiKey;
    this.fetchImpl = config.fetchImpl ?? globalThis.fetch.bind(globalThis);
    this.timeoutMs = config.timeoutMs ?? 20_000;
  }

  // ── transport ──────────────────────────────────────────────────────────────

  async request<T>(method: string, path: string, body?: unknown, auth = true): Promise<T> {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs);
    const headers: Record<string, string> = { Accept: "application/json" };
    if (auth) headers.Authorization = `Bearer ${this.apiKey}`;
    if (body !== undefined) headers["Content-Type"] = "application/json";

    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        method,
        headers,
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        cache: "no-store",
      });
    } catch (error) {
      const reason = controller.signal.aborted ? `timed out after ${this.timeoutMs}ms` : String(error);
      throw new NetworkError(`Could not reach ${this.baseUrl}: ${reason}`, error);
    } finally {
      clearTimeout(timer);
    }

    const text = await response.text();
    let parsed: unknown = undefined;
    if (text) {
      try {
        parsed = JSON.parse(text);
      } catch {
        parsed = undefined;
      }
    }

    if (!response.ok) {
      const err = (parsed as { error?: { message?: string; code?: string | null } } | undefined)?.error;
      // A non-JSON error body is usually the proxy, not the API — say which.
      const message = err?.message
        ?? (response.status === 502 || response.status === 504
          ? `The server's gateway could not reach the backend (${response.status}). It may be restarting.`
          : `Request failed (${response.status})`);
      throw errorForStatus(response.status, message, err?.code ?? null);
    }
    return parsed as T;
  }

  // ── health & identity ─────────────────────────────────────────────────────

  async health(): Promise<{ status: string }> {
    return this.request("GET", "/health", undefined, false);
  }

  /** Cheapest authenticated call: resolves if the key is accepted. */
  async verifyKey(): Promise<void> {
    await this.request<DataResponse<Template[]>>("GET", "/api/v1/templates");
  }

  // ── templates ──────────────────────────────────────────────────────────────

  async listTemplates(): Promise<Template[]> {
    return (await this.request<DataResponse<Template[]>>("GET", "/api/v1/templates")).data;
  }

  async getTemplate(id: string): Promise<Template> {
    return (await this.request<DataResponse<Template>>("GET", `/api/v1/templates/${encodeURIComponent(id)}`)).data;
  }

  async runTemplate(
    id: string,
    body: { inputs?: Record<string, unknown>; priority?: number; force?: boolean } = {},
  ): Promise<RunTemplateResult> {
    return (await this.request<DataResponse<RunTemplateResult>>(
      "POST", `/api/v1/templates/${encodeURIComponent(id)}/run`, { inputs: {}, ...body },
    )).data;
  }

  // ── attestations ──────────────────────────────────────────────────────────

  async listAttestations(): Promise<Attestation[]> {
    return (await this.request<DataResponse<Attestation[]>>("GET", "/api/v1/attestations")).data;
  }

  /** `version` must be the one shown to the user; a stale one is refused (409). */
  async acceptAttestation(id: string, version: string): Promise<Attestation> {
    return (await this.request<DataResponse<Attestation>>(
      "POST", `/api/v1/attestations/${encodeURIComponent(id)}/accept`, { version },
    )).data;
  }

  async withdrawAttestation(id: string): Promise<Attestation> {
    return (await this.request<DataResponse<Attestation>>(
      "POST", `/api/v1/attestations/${encodeURIComponent(id)}/withdraw`,
    )).data;
  }

  // ── runs ───────────────────────────────────────────────────────────────────

  async listRuns(params: { page?: number; status?: string; taskId?: string } = {}): Promise<PageResponse<Run>> {
    const q = new URLSearchParams();
    if (params.page) q.set("page", String(params.page));
    if (params.status) q.set("status", params.status);
    if (params.taskId) q.set("task_id", params.taskId);
    const qs = q.toString();
    return this.request("GET", `/api/v1/runs${qs ? `?${qs}` : ""}`);
  }

  async getRun(id: string, verbosity?: Verbosity): Promise<RunDetail> {
    const qs = verbosity ? `?verbosity=${verbosity}` : "";
    return (await this.request<DataResponse<RunDetail>>("GET", `/api/v1/runs/${encodeURIComponent(id)}${qs}`)).data;
  }

  async cancelRun(id: string): Promise<{ run_id: string; status: string }> {
    return (await this.request<DataResponse<{ run_id: string; status: string }>>(
      "POST", `/api/v1/runs/${encodeURIComponent(id)}/cancel`,
    )).data;
  }

  /** Full edition only — the run-only edition refuses it (403) by design. */
  async getRunSpans(id: string): Promise<SpanNode[]> {
    return (await this.request<DataResponse<SpanNode[]>>("GET", `/api/v1/runs/${encodeURIComponent(id)}/spans`)).data;
  }

  streamRun(
    runId: string,
    options: Omit<RunStreamOptions, "baseUrl" | "apiKey" | "runId" | "fetchImpl">,
  ): RunStreamHandle {
    return openRunStream({
      ...options,
      baseUrl: this.baseUrl,
      apiKey: this.apiKey,
      runId,
      fetchImpl: this.fetchImpl,
    });
  }

  // ── budget ─────────────────────────────────────────────────────────────────

  async usageSummary(days = 30): Promise<UsageSummary> {
    return (await this.request<DataResponse<UsageSummary>>("GET", `/api/v1/budget/usage?days=${days}`)).data;
  }
}
