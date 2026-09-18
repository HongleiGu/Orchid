// Mirrors the backend's response models. Kept by hand rather than generated:
// the surface a client uses is small, and a generator would drag the whole
// authoring API — agents, workflow-maker, skill-writer — into every client,
// including ones that must never call it.

export interface DataResponse<T> {
  data: T;
}

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
}

export interface PageResponse<T> {
  data: T[];
  meta: PageMeta;
}

export interface TemplateInput {
  name: string;
  type: string;
  label: string;
  description: string;
  default: unknown;
  required: boolean;
}

export interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  inputs: TemplateInput[];
  /** e.g. "attestation:securities_advisory" — why a template may be locked. */
  requires: string[];
}

export interface RunTemplateResult {
  run_id: string;
  template_id: string;
  task_id: string;
  status: string;
  inputs: Record<string, unknown>;
}

export interface Attestation {
  id: string;
  title: string;
  summary: string;
  text: string;
  version: string;
  locale: string;
  basis: string;
  requirement: string;
  accepted: boolean;
  /** May be older than `version` — that is "please re-confirm", not "never accepted". */
  accepted_version: string | null;
  accepted_at: string | null;
}

export type RunStatus = "pending" | "running" | "done" | "failed" | "cancelled";

export interface RunCost {
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  llm_calls: number;
}

export interface Run {
  id: string;
  task_id: string;
  agent_id: string | null;
  status: RunStatus | string;
  model_used: string | null;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  cost: RunCost;
}

export interface RunEvent {
  id?: number;
  run_id?: string;
  seq: number;
  type: string;
  agent: string | null;
  span_id?: string | null;
  parent_span_id?: string | null;
  payload: Record<string, unknown>;
  ts?: string;
}

export interface AgentCost extends RunCost {
  agent: string;
  model: string;
}

export interface RunDetail extends Run {
  verbosity: string;
  events: RunEvent[];
  cost_by_agent: AgentCost[];
  cost_unattributed_usd: number;
}

export interface SpanNode {
  span_id: string;
  parent_span_id: string | null;
  kind: string;
  agent: string | null;
  started_at: string | null;
  finished_at: string | null;
  status: string;
  cost_usd: number;
  input_tokens: number;
  output_tokens: number;
  llm_calls: number;
  subtree_cost_usd: number;
  subtree_input_tokens: number;
  subtree_output_tokens: number;
  subtree_llm_calls: number;
  subtree_share: number;
}

export interface UsageSummary {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  cost_usd: number;
  llm_calls: number;
  period_days: number;
}

export type Verbosity = "summary" | "info" | "debug";

export const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set(["done", "failed", "cancelled"]);

// ── Vault (OR-46) ────────────────────────────────────────────────────────────

export interface VaultProject {
  name: string;
  file_count: number;
  total_size: number;
  modified_at: string | null;
}

export interface VaultFile {
  name: string;
  project: string;
  size: number;
  modified_at: string;
  media_type: string;
  /** Whether readFile returns it inline. Binary files are download-only. */
  is_text: boolean;
}

export interface VaultFileContent {
  name: string;
  project: string;
  content: string;
  size: number;
  modified_at: string;
  media_type: string;
}

// ── Device pairing (OR-47) ───────────────────────────────────────────────────

export interface PairingCode {
  id: string;
  /** Formatted for display, e.g. "K9RX0-CFGP6". */
  code: string;
  expires_at: string;
  ttl_seconds: number;
}

export type PairingState = "pending" | "redeemed" | "expired";

export interface PairingStatus {
  id: string;
  status: PairingState;
  expires_at: string;
  redeemed_at: string | null;
  device_name: string | null;
}

export interface PairingRedemption {
  api_key: string;
  key_id: string;
  identifier: string;
}
