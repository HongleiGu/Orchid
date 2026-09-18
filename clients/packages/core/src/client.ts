import { errorForStatus, NetworkError } from "./errors";
import { openRunStream, type RunStreamHandle, type RunStreamOptions } from "./sse";
import type {
  Attestation,
  DataResponse,
  PageResponse,
  PairingCode,
  PairingRedemption,
  PairingStatus,
  Run,
  RunDetail,
  RunTemplateResult,
  SpanNode,
  Template,
  UsageSummary,
  VaultFile,
  VaultFileContent,
  VaultProject,
  Verbosity,
} from "./types";

/** A file fetched with its credentials, ready to save or share. */
export interface DownloadedFile {
  blob: Blob;
  filename: string;
  mediaType: string;
}

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

  // ── vault (OR-46) ────────────────────────────────────────────────────────────

  async vaultProjects(): Promise<VaultProject[]> {
    return (await this.request<DataResponse<VaultProject[]>>("GET", "/api/v1/vault/projects")).data;
  }

  async vaultFiles(project: string): Promise<VaultFile[]> {
    return (await this.request<DataResponse<VaultFile[]>>(
      "GET", `/api/v1/vault/projects/${encodeURIComponent(project)}`,
    )).data;
  }

  async vaultFile(project: string, filename: string): Promise<VaultFileContent> {
    return (await this.request<DataResponse<VaultFileContent>>(
      "GET", `/api/v1/vault/projects/${encodeURIComponent(project)}/${encodeURIComponent(filename)}`,
    )).data;
  }

  /**
   * Fetch a file with its credentials as a blob. A plain <a download> cannot be
   * used: it sends no Authorization header, so it would 401. The caller decides
   * what to do with the blob — Web Share on a phone, an object URL on desktop.
   */
  async downloadVaultFile(project: string, filename: string): Promise<DownloadedFile> {
    const path = `/api/v1/vault/projects/${encodeURIComponent(project)}/${encodeURIComponent(filename)}/download`;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), this.timeoutMs * 6); // files are larger than JSON
    let response: Response;
    try {
      response = await this.fetchImpl(`${this.baseUrl}${path}`, {
        headers: { Authorization: `Bearer ${this.apiKey}` },
        signal: controller.signal,
        cache: "no-store",
      });
    } catch (error) {
      throw new NetworkError(`Could not download ${filename}: ${String(error)}`, error);
    } finally {
      clearTimeout(timer);
    }
    if (!response.ok) {
      throw errorForStatus(response.status, `Download failed (${response.status})`, null);
    }
    return {
      blob: await response.blob(),
      filename,
      mediaType: response.headers.get("Content-Type") ?? "application/octet-stream",
    };
  }

  // ── device pairing (OR-47) ───────────────────────────────────────────────────

  /** Issue a code so another device can sign itself in. */
  async createPairing(): Promise<PairingCode> {
    return (await this.request<DataResponse<PairingCode>>("POST", "/api/v1/pairing")).data;
  }

  async pairingStatus(id: string): Promise<PairingStatus> {
    return (await this.request<DataResponse<PairingStatus>>(
      "GET", `/api/v1/pairing/${encodeURIComponent(id)}`,
    )).data;
  }

  /**
   * Redeem a code on a new device to obtain its own key. Static — no key yet —
   * so it does not go through the authenticated `request` path.
   */
  static async redeemPairing(
    baseUrl: string,
    code: string,
    deviceName: string,
    fetchImpl: typeof fetch = globalThis.fetch.bind(globalThis),
  ): Promise<PairingRedemption> {
    const root = baseUrl.replace(/\/+$/, "");
    let response: Response;
    try {
      response = await fetchImpl(`${root}/api/v1/pairing/redeem`, {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ code, device_name: deviceName }),
        cache: "no-store",
      });
    } catch (error) {
      throw new NetworkError(`Could not reach ${root}: ${String(error)}`, error);
    }
    const text = await response.text();
    let parsed: unknown;
    try { parsed = text ? JSON.parse(text) : undefined; } catch { parsed = undefined; }
    if (!response.ok) {
      const err = (parsed as { error?: { message?: string } } | undefined)?.error;
      throw errorForStatus(response.status, err?.message ?? `Pairing failed (${response.status})`, null);
    }
    return (parsed as DataResponse<PairingRedemption>).data;
  }
}
