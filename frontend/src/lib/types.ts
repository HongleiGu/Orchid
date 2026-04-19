// ── API response envelopes ───────────────────────────────────────────────────

export interface PageMeta {
  page: number;
  page_size: number;
  total: number;
}

export interface PageResponse<T> {
  data: T[];
  meta: PageMeta;
}

export interface DataResponse<T> {
  data: T;
}

// ── Domain models ────────────────────────────────────────────────────────────

export interface Agent {
  id: string;
  name: string;
  role: string;
  system_prompt: string;
  model: string | null;
  tools: string[];
  skills: string[];
  memory_strategy: string;
  reasoning: boolean;
  created_at: string;
  updated_at: string;
}

export interface AgentCreate {
  name: string;
  role?: string;
  system_prompt?: string;
  model?: string | null;
  tools?: string[];
  skills?: string[];
  memory_strategy?: string;
  reasoning?: boolean;
}

export type InputFieldType = "string" | "number" | "boolean" | "json";

export interface InputField {
  name: string;
  type: InputFieldType;
  label?: string;
  description?: string;
  required?: boolean;
  default?: unknown;
  options?: string[]; // for type="string" with a fixed set of choices
}

export type InputSchema = InputField[];

export interface Task {
  id: string;
  name: string;
  description: string;
  workflow_type: "single" | "dag" | "group" | "pipeline" | "passthrough";
  workflow_config: Record<string, unknown>;
  agent_id: string | null;
  inputs: Record<string, unknown>;
  input_schema: InputSchema;
  cron_expr: string | null;
  default_priority: number;
  status: "idle" | "scheduled" | "running" | "done" | "failed";
  last_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface TaskCreate {
  name: string;
  description?: string;
  workflow_type?: "single" | "dag" | "group" | "pipeline" | "passthrough";
  workflow_config?: Record<string, unknown>;
  agent_id?: string | null;
  inputs?: Record<string, unknown>;
  input_schema?: InputSchema;
  cron_expr?: string | null;
  default_priority?: number;
}

export interface TriggerOptions {
  params?: Record<string, unknown>;
  priority?: number;
  force?: boolean;
}

export interface BatchTriggerItem {
  params?: Record<string, unknown>;
  priority?: number;
}

export interface RunEvent {
  id: number;
  run_id: string;
  seq: number;
  type: string;
  agent: string | null;
  payload: Record<string, unknown>;
  ts: string;
}

export interface Run {
  id: string;
  task_id: string;
  agent_id: string | null;
  status: "pending" | "running" | "done" | "failed" | "cancelled";
  model_used: string | null;
  started_at: string | null;
  finished_at: string | null;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: string;
  events?: RunEvent[];
}

export interface ProviderInfo {
  name: string;
  key_set: boolean;
  base_url: string;
  reachable?: boolean;
}

export interface ModelInfo {
  id: string;
  provider: string;
  tools: boolean;
  vision: boolean;
  context: number;
  output_tokens: number;
}

export interface SecretInfo {
  key: string;
  is_set: boolean;
  masked: string;
}

export interface SecretUpdate {
  key: string;
  value: string;
}
