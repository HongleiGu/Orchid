import type {
  Agent,
  AgentCreate,
  BatchTriggerItem,
  DataResponse,
  ModelInfo,
  PageResponse,
  ProviderInfo,
  Run,
  SecretInfo,
  SecretUpdate,
  SpanNode,
  Task,
  TaskCreate,
  TriggerOptions,
} from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    ...init,
  });
  const json = await res.json();
  if (!res.ok) {
    const msg = json?.error?.message ?? res.statusText;
    throw new Error(msg);
  }
  return json as T;
}

export const api = {
  agents: {
    list: (page = 1) =>
      apiFetch<PageResponse<Agent>>(`/api/v1/agents?page=${page}`),
    get: (id: string) =>
      apiFetch<DataResponse<Agent>>(`/api/v1/agents/${id}`),
    create: (body: AgentCreate) =>
      apiFetch<DataResponse<Agent>>("/api/v1/agents", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: string, body: Partial<AgentCreate>) =>
      apiFetch<DataResponse<Agent>>(`/api/v1/agents/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    delete: (id: string) =>
      apiFetch<void>(`/api/v1/agents/${id}`, { method: "DELETE" }),
  },

  tasks: {
    list: (page = 1, status?: string) =>
      apiFetch<PageResponse<Task>>(
        `/api/v1/tasks?page=${page}${status ? `&status=${status}` : ""}`
      ),
    get: (id: string) =>
      apiFetch<DataResponse<Task>>(`/api/v1/tasks/${id}`),
    create: (body: TaskCreate) =>
      apiFetch<DataResponse<Task>>("/api/v1/tasks", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    update: (id: string, body: Partial<TaskCreate>) =>
      apiFetch<DataResponse<Task>>(`/api/v1/tasks/${id}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    delete: (id: string) =>
      apiFetch<void>(`/api/v1/tasks/${id}`, { method: "DELETE" }),
    trigger: (id: string, options: TriggerOptions = {}) =>
      apiFetch<DataResponse<{ run_id: string; task_id: string; status: string; priority: number }>>(
        `/api/v1/tasks/${id}/trigger`,
        {
          method: "POST",
          body: JSON.stringify({
            params: options.params ?? {},
            priority: options.priority ?? null,
            force: options.force ?? false,
          }),
        }
      ),
    triggerBatch: (id: string, runs: BatchTriggerItem[]) =>
      apiFetch<DataResponse<{ task_id: string; run_ids: string[] }>>(
        `/api/v1/tasks/${id}/trigger/batch`,
        { method: "POST", body: JSON.stringify({ runs }) }
      ),
  },

  runs: {
    list: (page = 1, taskId?: string, status?: string) => {
      const params = new URLSearchParams({ page: String(page) });
      if (taskId) params.set("task_id", taskId);
      if (status) params.set("status", status);
      return apiFetch<PageResponse<Run>>(`/api/v1/runs?${params}`);
    },
    get: (id: string) => apiFetch<DataResponse<Run>>(`/api/v1/runs/${id}`),
    cancel: (id: string) =>
      apiFetch<DataResponse<{ run_id: string; status: string }>>(
        `/api/v1/runs/${id}/cancel`,
        { method: "POST" }
      ),
    spans: (id: string) =>
      apiFetch<DataResponse<SpanNode[]>>(`/api/v1/runs/${id}/spans`),
    cancelSpan: (runId: string, spanId: string) =>
      apiFetch<DataResponse<{ span_id: string; cancelled: boolean }>>(
        `/api/v1/runs/${runId}/spans/${spanId}/cancel`,
        { method: "POST" }
      ),
  },

  providers: {
    list: () => apiFetch<DataResponse<ProviderInfo[]>>("/api/v1/providers"),
    secrets: () => apiFetch<DataResponse<SecretInfo[]>>("/api/v1/providers/secrets"),
    updateSecrets: (body: SecretUpdate[]) =>
      apiFetch<DataResponse<SecretInfo[]>>("/api/v1/providers/secrets", {
        method: "PUT",
        body: JSON.stringify(body),
      }),
  },

  models: {
    list: () => apiFetch<DataResponse<ModelInfo[]>>("/api/v1/models"),
  },

  marketplace: {
    installed: () =>
      apiFetch<DataResponse<{ id: string; npm_name: string; version: string; pkg_type: string; registered_name: string; description: string; enabled: boolean; installed_at: string }[]>>(
        "/api/v1/marketplace/installed"
      ),
    install: (pkg: string) =>
      apiFetch<DataResponse<{ success: boolean; name: string; npm_name: string; pkg_type: string; version: string; error?: string }>>(
        "/api/v1/marketplace/install",
        { method: "POST", body: JSON.stringify({ package: pkg }) },
      ),
    uninstall: (pkg: string) =>
      apiFetch<DataResponse<{ npm_name: string; status: string }>>(
        "/api/v1/marketplace/uninstall",
        { method: "POST", body: JSON.stringify({ package: pkg }) },
      ),
    toggle: (pkg: string, enabled: boolean) =>
      apiFetch<DataResponse<{ npm_name: string; enabled: boolean }>>(
        "/api/v1/marketplace/toggle",
        { method: "POST", body: JSON.stringify({ package: pkg, enabled }) },
      ),
    runnerSkills: () =>
      apiFetch<DataResponse<{ name: string; description: string; pkg_type: string }[]>>(
        "/api/v1/marketplace/runner/skills"
      ),
  },

  budget: {
    usage: (days = 30) =>
      apiFetch<DataResponse<{ input_tokens: number; output_tokens: number; total_tokens: number; cost_usd: number; llm_calls: number; period_days: number }>>(
        `/api/v1/budget/usage?days=${days}`
      ),
    byModel: (days = 30) =>
      apiFetch<DataResponse<{ model: string; input_tokens: number; output_tokens: number; cost_usd: number; calls: number }[]>>(
        `/api/v1/budget/usage/by-model?days=${days}`
      ),
    byAgent: (days = 30) =>
      apiFetch<DataResponse<{ agent: string; input_tokens: number; output_tokens: number; cost_usd: number; calls: number }[]>>(
        `/api/v1/budget/usage/by-agent?days=${days}`
      ),
    runUsage: (runId: string) =>
      apiFetch<DataResponse<{ input_tokens: number; output_tokens: number; tokens: number; cost: number }>>(
        `/api/v1/budget/usage/run/${runId}`
      ),
    limits: () =>
      apiFetch<DataResponse<{ id: string; scope_type: string; scope_id: string; max_tokens_per_run: number | null; max_cost_per_run: number | null; max_cost_per_day: number | null; max_cost_per_month: number | null }[]>>(
        "/api/v1/budget/limits"
      ),
    setLimit: (body: { scope_type: string; scope_id: string; max_tokens_per_run?: number | null; max_cost_per_run?: number | null; max_cost_per_day?: number | null; max_cost_per_month?: number | null }) =>
      apiFetch<DataResponse<unknown>>("/api/v1/budget/limits", {
        method: "POST",
        body: JSON.stringify(body),
      }),
    deleteLimit: (id: string) =>
      apiFetch<void>(`/api/v1/budget/limits/${id}`, { method: "DELETE" }),
    pricing: () =>
      apiFetch<DataResponse<{ model: string; input_per_m: number; output_per_m: number }[]>>(
        "/api/v1/budget/pricing"
      ),
  },

  vault: {
    projects: () =>
      apiFetch<DataResponse<{ name: string; file_count: number; total_size: number }[]>>("/api/v1/vault/projects"),
    files: (project: string) =>
      apiFetch<DataResponse<{ name: string; project: string; size: number; modified_at: string }[]>>(
        `/api/v1/vault/projects/${project}`
      ),
    read: (project: string, filename: string) =>
      apiFetch<DataResponse<{ name: string; project: string; content: string; size: number; modified_at: string }>>(
        `/api/v1/vault/projects/${project}/${filename}`
      ),
    delete: (project: string, filename: string) =>
      apiFetch<void>(`/api/v1/vault/projects/${project}/${filename}`, { method: "DELETE" }),
  },

  registry: {
    all: () =>
      apiFetch<DataResponse<{ name: string; description: string; type: string; source: string; parameters: Record<string, unknown> }[]>>(
        "/api/v1/registry/all"
      ),
  },

  config: {
    export: () => apiFetch<DataResponse<unknown>>("/api/v1/config/export"),
    exportAgents: () => apiFetch<DataResponse<unknown>>("/api/v1/config/export/agents"),
    exportTasks: () => apiFetch<DataResponse<unknown>>("/api/v1/config/export/tasks"),
    import: (body: unknown) =>
      apiFetch<DataResponse<{ skills_installed: number; skills_skipped: number; agents_created: number; agents_skipped: number; tasks_created: number; tasks_skipped: number; errors: string[] }>>(
        "/api/v1/config/import",
        { method: "POST", body: JSON.stringify(body) },
      ),
  },
};

export function wsUrl(runId: string): string {
  const ws = (process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000");
  return `${ws}/api/v1/runs/${runId}/stream`;
}
