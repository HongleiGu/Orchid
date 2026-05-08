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

export type WorkflowType = "single" | "dag" | "group";

export interface Task {
  id: string;
  name: string;
  description: string;
  workflow_type: WorkflowType;
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
  workflow_type?: WorkflowType;
  workflow_config?: Record<string, unknown>;
  agent_id?: string | null;
  inputs?: Record<string, unknown>;
  input_schema?: InputSchema;
  cron_expr?: string | null;
  default_priority?: number;
}

export interface PipelineAgentConfig {
  name: string;
  role?: string;
  system_prompt?: string;
  model?: string | null;
  tools?: string[];
  skills?: string[];
  memory_strategy?: string;
  reasoning?: boolean;
}

export interface PipelineTaskConfig {
  name: string;
  description?: string;
  workflow_type?: WorkflowType;
  workflow_config?: Record<string, unknown>;
  agent_name?: string | null;
  inputs?: Record<string, unknown>;
  input_schema?: InputSchema;
  cron_expr?: string | null;
  default_priority?: number;
}

export interface PipelineConfig {
  skills: string[];
  agents: PipelineAgentConfig[];
  tasks: PipelineTaskConfig[];
}

export interface SkillNeed {
  name: string;
  reason: string;
  alternative?: string | null;
}

export interface WorkflowDraftRequest {
  description: string;
  name?: string;
  model?: string;
}

export interface WorkflowDraft {
  plan: string[];
  workflow: PipelineConfig;
  required_skills: string[];
  optional_skills: string[];
  missing_required_skills: SkillNeed[];
  missing_optional_skills: SkillNeed[];
  notes: string[];
}

export interface SkillWriterRequest {
  description: string;
  name?: string;
  model?: string;
}

export interface SkillEnvVar {
  name: string;
  required: boolean;
  description: string;
  example: string;
}

export interface SkillFile {
  path: string;
  content: string;
}

export interface SkillDraft {
  package_name: string;
  skill_name: string;
  summary: string;
  env_vars: SkillEnvVar[];
  files: SkillFile[];
  install_notes: string[];
  test_plan: string[];
  questions: string[];
  limitations: string[];
}

export interface SaveSkillDraftResponse {
  package_name: string;
  directory: string;
  install_target: string;
  valid: boolean;
  validation_error?: string | null;
}

// ── DAG workflow_config shape ───────────────────────────────────────────────

export interface DagNodeConfig {
  name: string;
  agent_id: string;
  inputs?: Record<string, unknown>;   // optional JSON-Schema-shaped contract
  outputs?: Record<string, unknown>;
  // Editor-only positional state. Backend ignores these fields.
  position?: { x: number; y: number };
}

export interface DagEdgeConfig {
  source: string;
  target: string;
  /** Optional Python expression evaluated against `output` on the source.
   *  Edge fires only when truthy. Empty / undefined = unconditional. */
  if?: string;
}

export interface DagWorkflowConfig {
  nodes: DagNodeConfig[];
  edges: DagEdgeConfig[];
  entry?: string;
  auto_save?: boolean;
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
  span_id?: string | null;
  parent_span_id?: string | null;
  payload: Record<string, unknown>;
  ts: string;
}

export type SpanKind = "agent" | "dag_node" | "peer_call";
export type SpanStatus = "running" | "done" | "cancelled" | "failed";

export interface SpanNode {
  span_id: string;
  parent_span_id: string | null;
  kind: SpanKind;
  agent: string | null;
  started_at: string | null;
  finished_at: string | null;
  status: SpanStatus;
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
