"use client";

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import type { AgentCreate, SecretUpdate, TaskCreate } from "./types";

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
    mutationFn: ({ id, params }: { id: string; params?: Record<string, unknown> }) =>
      api.tasks.trigger(id, params),
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
