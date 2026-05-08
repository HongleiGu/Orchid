"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { AgentCreate, BatchTriggerItem, SecretUpdate, SkillDraft, SkillWriterRequest, TaskCreate, TriggerOptions, WorkflowDraftRequest } from "./types";

// ── Agents ───────────────────────────────────────────────────────────────────

export function useAgents(page = 1) {
  return useQuery({
    queryKey: ["agents", page],
    queryFn: () => api.agents.list(page),
  });
}

export function useAgent(id: string) {
  return useQuery({
    queryKey: ["agents", id],
    queryFn: () => api.agents.get(id),
    enabled: !!id,
  });
}

export function useCreateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AgentCreate) => api.agents.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
}

export function useUpdateAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<AgentCreate> }) =>
      api.agents.update(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
}

export function useDeleteAgent() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.agents.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["agents"] }),
  });
}

// ── Tasks ────────────────────────────────────────────────────────────────────

export function useTasks(page = 1) {
  return useQuery({
    queryKey: ["tasks", page],
    queryFn: () => api.tasks.list(page),
  });
}

export function useCreateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: TaskCreate) => api.tasks.create(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}

export function useUpdateTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, body }: { id: string; body: Partial<TaskCreate> }) =>
      api.tasks.update(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}

export function useDeleteTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.tasks.delete(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["tasks"] }),
  });
}

export function useTriggerTask() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, ...options }: { id: string } & TriggerOptions) =>
      api.tasks.trigger(id, options),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

export function useTriggerTaskBatch() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, runs }: { id: string; runs: BatchTriggerItem[] }) =>
      api.tasks.triggerBatch(id, runs),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["runs"] });
    },
  });
}

// ── Runs ─────────────────────────────────────────────────────────────────────

export function useRuns(page = 1, taskId?: string) {
  return useQuery({
    queryKey: ["runs", page, taskId],
    queryFn: () => api.runs.list(page, taskId),
  });
}

export function useRun(id: string) {
  return useQuery({
    queryKey: ["runs", id],
    queryFn: () => api.runs.get(id),
    enabled: !!id,
    refetchInterval: (query) => {
      const status = query.state.data?.data?.status;
      return status === "running" || status === "pending" ? 2000 : false;
    },
  });
}

export function useCancelRun() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.runs.cancel(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["runs"] }),
  });
}

export function useRunSpans(runId: string, options?: { refetchInterval?: number | false }) {
  return useQuery({
    queryKey: ["runs", runId, "spans"],
    queryFn: () => api.runs.spans(runId),
    enabled: !!runId,
    refetchInterval: options?.refetchInterval ?? false,
  });
}

export function useCancelSpan() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ runId, spanId }: { runId: string; spanId: string }) =>
      api.runs.cancelSpan(runId, spanId),
    onSuccess: (_, vars) => {
      qc.invalidateQueries({ queryKey: ["runs", vars.runId, "spans"] });
    },
  });
}

// ── Workflow Maker ───────────────────────────────────────────────────────────

export function useDraftWorkflow() {
  return useMutation({
    mutationFn: (body: WorkflowDraftRequest) => api.workflowMaker.draft(body),
  });
}

export function useImportConfig() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: unknown) => api.config.import(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
      qc.invalidateQueries({ queryKey: ["registry"] });
    },
  });
}

// ── Skill Writer ─────────────────────────────────────────────────────────────

export function useDraftSkill() {
  return useMutation({
    mutationFn: (body: SkillWriterRequest) => api.skillWriter.draft(body),
  });
}

export function useSaveSkillDraft() {
  return useMutation({
    mutationFn: (draft: SkillDraft) =>
      api.skillWriter.save({
        package_name: draft.package_name,
        files: draft.files,
      }),
  });
}

// ── Single agent loader (used by the DAG editor) ─────────────────────────────

export function useAllAgents() {
  // The agents API is paginated at 20/page. The DAG editor needs a flat list
  // to populate node pickers; for now we fetch the first page and trust that
  // <20 agents covers the realistic case. Bump to a paginating loader if a
  // user actually crosses the threshold.
  return useAgents(1);
}

// ── Models & Providers ───────────────────────────────────────────────────────

export function useModels() {
  return useQuery({
    queryKey: ["models"],
    queryFn: () => api.models.list(),
    staleTime: 60_000,
  });
}

export function useProviders() {
  return useQuery({
    queryKey: ["providers"],
    queryFn: () => api.providers.list(),
    staleTime: 60_000,
  });
}

export function useSecrets() {
  return useQuery({
    queryKey: ["secrets"],
    queryFn: () => api.providers.secrets(),
  });
}

export function useUpdateSecrets() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SecretUpdate[]) => api.providers.updateSecrets(body),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["secrets"] });
      qc.invalidateQueries({ queryKey: ["providers"] });
    },
  });
}
