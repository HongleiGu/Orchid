"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import { Pencil, Play, Plus, Trash2 } from "lucide-react";
import { Badge, Button, Card, Empty, Input, Modal, Select, Textarea } from "@/components/ui";
import { useAgents, useCreateTask, useDeleteTask, useTasks, useTriggerTask, useUpdateTask } from "@/lib/hooks";
import { formatDate } from "@/lib/utils";
import type { Task, TaskCreate } from "@/lib/types";

const BLANK: TaskCreate = {
  name: "",
  description: "",
  workflow_type: "single",
  workflow_config: {},
  agent_id: null,
  inputs: {},
  cron_expr: null,
};

export default function TasksPage() {
  const router = useRouter();
  const [page, setPage] = useState(1);
  const { data, isLoading } = useTasks(page);
  const agents = useAgents();

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Task | null>(null);
  const [form, setForm] = useState<TaskCreate>(BLANK);
  // Group config helpers
  const [orchId, setOrchId] = useState("");
  const [workerIds, setWorkerIds] = useState("");
  const [maxTurnsPerAgent, setMaxTurnsPerAgent] = useState(5);
  const [maxTotalTurns, setMaxTotalTurns] = useState(20);
  // Pipeline config helpers
  const [pipelineSteps, setPipelineSteps] = useState("");
  // Trigger-with-params
  const [triggerModalOpen, setTriggerModalOpen] = useState(false);
  const [triggerTaskId, setTriggerTaskId] = useState("");
  const [triggerParams, setTriggerParams] = useState("");

  const create = useCreateTask();
  const update = useUpdateTask();
  const del = useDeleteTask();
  const trigger = useTriggerTask();

  function openCreate() {
    setEditing(null);
    setForm(BLANK);
    setOrchId("");
    setWorkerIds("");
    setMaxTurnsPerAgent(5);
    setMaxTotalTurns(20);
    setPipelineSteps("");
    setModalOpen(true);
  }

  function openEdit(t: Task) {
    setEditing(t);
    setForm({
      name: t.name,
      description: t.description,
      workflow_type: t.workflow_type,
      workflow_config: t.workflow_config,
      agent_id: t.agent_id,
      inputs: t.inputs,
      cron_expr: t.cron_expr,
    });
    const cfg = t.workflow_config as Record<string, unknown>;
    setOrchId((cfg.orchestrator_id as string) ?? "");
    setWorkerIds(((cfg.worker_ids as string[]) ?? []).join(", "));
    setMaxTurnsPerAgent((cfg.max_turns_per_agent as number) ?? 5);
    setMaxTotalTurns((cfg.max_total_turns as number) ?? 20);
    // Pipeline
    const steps = (cfg.steps as { task_name: string }[]) ?? [];
    setPipelineSteps(steps.map((s) => s.task_name).join("\n"));
    setModalOpen(true);
  }

  function buildForm(): TaskCreate {
    const f = { ...form };
    if (f.workflow_type === "group") {
      f.workflow_config = {
        orchestrator_id: orchId,
        worker_ids: workerIds.split(",").map((s) => s.trim()).filter(Boolean),
        max_turns_per_agent: maxTurnsPerAgent,
        max_total_turns: maxTotalTurns,
      };
      f.agent_id = null;
    } else if (f.workflow_type === "pipeline") {
      const stepNames = pipelineSteps.split("\n").map((s) => s.trim()).filter(Boolean);
      f.workflow_config = {
        steps: stepNames.map((name) => ({ task_name: name })),
      };
      f.agent_id = null;
    }
    return f;
  }

  async function handleSubmit() {
    const body = buildForm();
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, body });
        toast.success("Task updated");
      } else {
        await create.mutateAsync(body);
        toast.success("Task created");
      }
      setModalOpen(false);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  function openTrigger(taskId: string) {
    setTriggerTaskId(taskId);
    setTriggerParams("");
    setTriggerModalOpen(true);
  }

  async function handleTrigger(taskId: string, params?: Record<string, unknown>) {
    try {
      const res = await trigger.mutateAsync({ id: taskId, params });
      toast.success("Run started");
      router.push(`/runs/${res.data.run_id}`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  async function handleTriggerWithParams() {
    let params: Record<string, unknown> = {};
    if (triggerParams.trim()) {
      try {
        params = JSON.parse(triggerParams);
      } catch {
        toast.error("Invalid JSON params");
        return;
      }
    }
    setTriggerModalOpen(false);
    await handleTrigger(triggerTaskId, params);
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this task?")) return;
    try {
      await del.mutateAsync(id);
      toast.success("Task deleted");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  const agentList = agents.data?.data ?? [];

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Tasks</h1>
        <Button onClick={openCreate} size="sm">
          <Plus size={16} className="mr-1.5" /> New task
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted">Loading…</p>}
      {data && data.data.length === 0 && <Empty message="No tasks yet." />}

      <div className="grid gap-3">
        {data?.data.map((t) => (
          <Card key={t.id} className="flex items-start justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-semibold">{t.name}</span>
                <Badge value={t.status} />
                <Badge value={t.workflow_type} />
              </div>
              <p className="text-sm text-muted">{t.description || "No description"}</p>
              {t.cron_expr && <p className="text-xs text-accent mt-1">Cron: {t.cron_expr}</p>}
              <p className="text-xs text-muted mt-1">Last run: {formatDate(t.last_run_at)}</p>
            </div>
            <div className="flex gap-1 ml-4 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => handleTrigger(t.id)} disabled={t.status === "running"} title="Run">
                <Play size={14} className="text-success" />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => openTrigger(t.id)} disabled={t.status === "running"} title="Run with params">
                <span className="text-xs text-accent font-mono">{"{ }"}</span>
              </Button>
              <Button variant="ghost" size="sm" onClick={() => openEdit(t)}>
                <Pencil size={14} />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => handleDelete(t.id)}>
                <Trash2 size={14} className="text-danger" />
              </Button>
            </div>
          </Card>
        ))}
      </div>

      {data && data.meta.total > data.meta.page_size && (
        <div className="flex gap-2 justify-center mt-4">
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Button>
          <span className="text-sm text-muted py-1.5">Page {page}</span>
          <Button variant="secondary" size="sm" disabled={page * data.meta.page_size >= data.meta.total} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}

      {/* Create / Edit modal */}
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? "Edit Task" : "New Task"}>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted">Name</label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. Research AI agents" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted">Description</label>
            <Textarea
              rows={2}
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>
          <div>
            <label className="text-xs font-medium text-muted">Workflow type</label>
            <Select
              value={form.workflow_type}
              onChange={(e) => setForm({ ...form, workflow_type: e.target.value as TaskCreate["workflow_type"] })}
            >
              <option value="single">Single agent</option>
              <option value="group">Collaborative group</option>
              <option value="dag">DAG pipeline</option>
              <option value="pipeline">Chained pipeline</option>
            </Select>
          </div>

          {form.workflow_type === "single" && (
            <div>
              <label className="text-xs font-medium text-muted">Agent</label>
              <Select value={form.agent_id ?? ""} onChange={(e) => setForm({ ...form, agent_id: e.target.value || null })}>
                <option value="">— select agent —</option>
                {agentList.map((a) => (
                  <option key={a.id} value={a.id}>{a.name} ({a.role})</option>
                ))}
              </Select>
            </div>
          )}

          {form.workflow_type === "group" && (
            <>
              <div>
                <label className="text-xs font-medium text-muted">Orchestrator</label>
                <Select value={orchId} onChange={(e) => setOrchId(e.target.value)}>
                  <option value="">— select orchestrator —</option>
                  {agentList.map((a) => (
                    <option key={a.id} value={a.id}>{a.name} ({a.role})</option>
                  ))}
                </Select>
              </div>
              <div>
                <label className="text-xs font-medium text-muted">Worker IDs (comma-separated)</label>
                <Input
                  value={workerIds}
                  onChange={(e) => setWorkerIds(e.target.value)}
                  placeholder="Paste agent IDs separated by commas"
                />
                {agentList.filter((a) => a.role === "worker").length > 0 && (
                  <div className="flex flex-wrap gap-1 mt-1">
                    {agentList.filter((a) => a.role === "worker").map((a) => (
                      <button
                        key={a.id}
                        type="button"
                        className="text-xs bg-accent/10 text-accent px-2 py-0.5 rounded hover:bg-accent/20"
                        onClick={() => {
                          const ids = workerIds.split(",").map((s) => s.trim()).filter(Boolean);
                          if (!ids.includes(a.id)) {
                            setWorkerIds([...ids, a.id].join(", "));
                          }
                        }}
                      >
                        + {a.name}
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-xs font-medium text-muted">Max turns per agent</label>
                  <Input
                    type="number"
                    min={1}
                    max={50}
                    value={maxTurnsPerAgent}
                    onChange={(e) => setMaxTurnsPerAgent(Number(e.target.value) || 5)}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium text-muted">Max total turns</label>
                  <Input
                    type="number"
                    min={1}
                    max={100}
                    value={maxTotalTurns}
                    onChange={(e) => setMaxTotalTurns(Number(e.target.value) || 20)}
                  />
                </div>
              </div>
            </>
          )}

          {form.workflow_type === "pipeline" && (
            <div>
              <label className="text-xs font-medium text-muted">
                Pipeline steps (one task name per line, executed in order)
              </label>
              <Textarea
                rows={4}
                value={pipelineSteps}
                onChange={(e) => setPipelineSteps(e.target.value)}
                placeholder={"Fetch AI Papers\nResearch Papers\nWrite Blog Post"}
              />
              <p className="text-xs text-muted mt-1">
                Each step runs the named task. Output of step N is passed as
                <code className="bg-background px-1 rounded">previous_output</code> to step N+1.
              </p>
            </div>
          )}

          <div>
            <label className="text-xs font-medium text-muted">Cron expression (optional)</label>
            <Input
              value={form.cron_expr ?? ""}
              onChange={(e) => setForm({ ...form, cron_expr: e.target.value || null })}
              placeholder="*/5 * * * *"
            />
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSubmit} disabled={!form.name || create.isPending || update.isPending}>
              {editing ? "Save" : "Create"}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Trigger with params modal */}
      <Modal open={triggerModalOpen} onClose={() => setTriggerModalOpen(false)} title="Run with parameters">
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted">
              Runtime parameters (JSON, merged with task defaults)
            </label>
            <Textarea
              rows={5}
              value={triggerParams}
              onChange={(e) => setTriggerParams(e.target.value)}
              placeholder={'{\n  "topic": "multi-agent LLM frameworks",\n  "max_papers": 5\n}'}
              className="font-mono text-xs"
            />
          </div>
          <div className="flex justify-end gap-2">
            <Button variant="secondary" onClick={() => setTriggerModalOpen(false)}>Cancel</Button>
            <Button onClick={handleTriggerWithParams}>
              <Play size={14} className="mr-1.5" /> Run
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
