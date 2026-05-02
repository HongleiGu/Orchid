"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import toast from "react-hot-toast";
import { Copy, Network, Pencil, Play, Plus, Trash2, Layers } from "lucide-react";
import { Badge, Button, Card, Empty, Input, Modal, Select, Textarea } from "@/components/ui";
import {
  useAgents,
  useCreateTask,
  useDeleteTask,
  useTasks,
  useTriggerTask,
  useTriggerTaskBatch,
  useUpdateTask,
} from "@/lib/hooks";
import { formatDate } from "@/lib/utils";
import type {
  BatchTriggerItem,
  InputField,
  InputFieldType,
  InputSchema,
  Task,
  TaskCreate,
} from "@/lib/types";

const BLANK: TaskCreate = {
  name: "",
  description: "",
  workflow_type: "single",
  workflow_config: {},
  agent_id: null,
  inputs: {},
  input_schema: [],
  cron_expr: null,
  default_priority: 0,
};

const FIELD_TYPES: InputFieldType[] = ["string", "number", "boolean", "json"];

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
  // Trigger modal
  const [triggerModalOpen, setTriggerModalOpen] = useState(false);
  const [triggerTask, setTriggerTask] = useState<Task | null>(null);
  const [triggerMode, setTriggerMode] = useState<"single" | "batch">("single");
  const [triggerValues, setTriggerValues] = useState<Record<string, unknown>>({});
  const [triggerJson, setTriggerJson] = useState("");
  const [triggerPriority, setTriggerPriority] = useState<string>("");
  const [batchJson, setBatchJson] = useState("");
  // Schema-driven batch: list of {values, priority} items
  const [batchItems, setBatchItems] = useState<
    { values: Record<string, unknown>; priority: string }[]
  >([]);

  const create = useCreateTask();
  const update = useUpdateTask();
  const del = useDeleteTask();
  const trigger = useTriggerTask();
  const triggerBatch = useTriggerTaskBatch();

  function openCreate() {
    setEditing(null);
    setForm(BLANK);
    setOrchId("");
    setWorkerIds("");
    setMaxTurnsPerAgent(5);
    setMaxTotalTurns(20);
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
      input_schema: t.input_schema ?? [],
      cron_expr: t.cron_expr,
      default_priority: t.default_priority ?? 0,
    });
    const cfg = t.workflow_config as Record<string, unknown>;
    setOrchId((cfg.orchestrator_id as string) ?? "");
    setWorkerIds(((cfg.worker_ids as string[]) ?? []).join(", "));
    setMaxTurnsPerAgent((cfg.max_turns_per_agent as number) ?? 5);
    setMaxTotalTurns((cfg.max_total_turns as number) ?? 20);
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
    } else if (f.workflow_type === "dag") {
      // DAG nodes/edges are authored in the visual editor at /tasks/{id}/dag.
      // On create we leave the config empty; the user opens the editor to fill it in.
      if (!f.workflow_config || Object.keys(f.workflow_config).length === 0) {
        f.workflow_config = { nodes: [], edges: [] };
      }
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

  function seedSchemaValues(t: Task): Record<string, unknown> {
    const seed: Record<string, unknown> = {};
    for (const f of t.input_schema ?? []) {
      const taskDefault = (t.inputs ?? {})[f.name];
      seed[f.name] = taskDefault !== undefined ? taskDefault : f.default;
    }
    return seed;
  }

  function openTrigger(t: Task) {
    setTriggerTask(t);
    setTriggerMode("single");
    setTriggerJson("");
    setBatchJson("");
    setTriggerPriority("");
    const seed = seedSchemaValues(t);
    setTriggerValues(seed);
    setBatchItems([{ values: { ...seed }, priority: "" }]);
    setTriggerModalOpen(true);
  }

  async function quickTrigger(t: Task) {
    // No params, default priority — straight to runs page.
    try {
      const res = await trigger.mutateAsync({ id: t.id });
      toast.success("Run queued");
      router.push(`/runs/${res.data.run_id}`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  function parseJsonField(field: InputField, raw: unknown): unknown {
    if (field.type !== "json") return raw;
    if (raw === undefined || raw === null || raw === "") return field.required ? raw : undefined;
    if (typeof raw !== "string") return raw;
    return JSON.parse(raw);
  }

  async function handleSingleTrigger() {
    if (!triggerTask) return;
    let params: Record<string, unknown> = {};
    const schema = triggerTask.input_schema ?? [];

    if (schema.length > 0) {
      try {
        for (const field of schema) {
          const v = triggerValues[field.name];
          const parsed = parseJsonField(field, v);
          if (parsed === undefined) continue;
          params[field.name] = parsed;
        }
      } catch (e) {
        toast.error(`Invalid JSON in field: ${e instanceof Error ? e.message : "parse error"}`);
        return;
      }
    } else if (triggerJson.trim()) {
      try {
        params = JSON.parse(triggerJson);
      } catch {
        toast.error("Invalid JSON params");
        return;
      }
    }

    const priority = triggerPriority.trim() === "" ? undefined : Number(triggerPriority);
    if (priority !== undefined && Number.isNaN(priority)) {
      toast.error("Priority must be a number");
      return;
    }

    setTriggerModalOpen(false);
    try {
      const res = await trigger.mutateAsync({ id: triggerTask.id, params, priority });
      toast.success("Run queued");
      router.push(`/runs/${res.data.run_id}`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  async function handleBatchTrigger() {
    if (!triggerTask) return;
    const schema = triggerTask.input_schema ?? [];
    let runs: BatchTriggerItem[] = [];

    if (schema.length > 0) {
      // Schema-driven: build runs from batchItems
      if (batchItems.length === 0) {
        toast.error("No batch items");
        return;
      }
      try {
        for (let i = 0; i < batchItems.length; i++) {
          const item = batchItems[i];
          const params: Record<string, unknown> = {};
          for (const field of schema) {
            const v = item.values[field.name];
            const parsed = parseJsonField(field, v);
            if (parsed === undefined) continue;
            params[field.name] = parsed;
          }
          const prio = item.priority.trim() === "" ? undefined : Number(item.priority);
          if (prio !== undefined && Number.isNaN(prio)) {
            toast.error(`Item ${i + 1}: priority must be a number`);
            return;
          }
          runs.push({ params, priority: prio });
        }
      } catch (e) {
        toast.error(`Invalid JSON in field: ${e instanceof Error ? e.message : "parse error"}`);
        return;
      }
    } else {
      // No schema: parse the JSON textarea
      if (!batchJson.trim()) {
        toast.error("Batch JSON is empty");
        return;
      }
      let parsed: unknown;
      try {
        parsed = JSON.parse(batchJson);
      } catch {
        toast.error("Invalid JSON");
        return;
      }
      if (!Array.isArray(parsed) || parsed.length === 0) {
        toast.error("Expected a non-empty JSON array");
        return;
      }
      runs = parsed.map((item) => {
        const obj = (item ?? {}) as Record<string, unknown>;
        if ("params" in obj || "priority" in obj) {
          return {
            params: (obj.params as Record<string, unknown>) ?? {},
            priority: typeof obj.priority === "number" ? obj.priority : undefined,
          };
        }
        return { params: obj };
      });
    }

    setTriggerModalOpen(false);
    try {
      const res = await triggerBatch.mutateAsync({ id: triggerTask.id, runs });
      toast.success(`Queued ${res.data.run_ids.length} runs`);
      router.push("/runs");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  // ── Batch list helpers ────────────────────────────────────────────────────
  function addBatchItem(cloneFrom?: number) {
    if (!triggerTask) return;
    const seed =
      cloneFrom !== undefined && batchItems[cloneFrom]
        ? { ...batchItems[cloneFrom].values }
        : seedSchemaValues(triggerTask);
    const priority =
      cloneFrom !== undefined && batchItems[cloneFrom]
        ? batchItems[cloneFrom].priority
        : "";
    setBatchItems([...batchItems, { values: seed, priority }]);
  }

  function removeBatchItem(idx: number) {
    setBatchItems(batchItems.filter((_, i) => i !== idx));
  }

  function setBatchItemValue(idx: number, name: string, value: unknown) {
    const next = batchItems.map((it, i) =>
      i === idx ? { ...it, values: { ...it.values, [name]: value } } : it,
    );
    setBatchItems(next);
  }

  function setBatchItemPriority(idx: number, value: string) {
    const next = batchItems.map((it, i) => (i === idx ? { ...it, priority: value } : it));
    setBatchItems(next);
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
  const schema: InputSchema = form.input_schema ?? [];

  const triggerSchema = useMemo<InputSchema>(
    () => triggerTask?.input_schema ?? [],
    [triggerTask],
  );

  function setSchemaField(idx: number, patch: Partial<InputField>) {
    const next = [...schema];
    next[idx] = { ...next[idx], ...patch };
    setForm({ ...form, input_schema: next });
  }

  function addSchemaField() {
    const next: InputField[] = [...schema, { name: "", type: "string" }];
    setForm({ ...form, input_schema: next });
  }

  function removeSchemaField(idx: number) {
    const next = schema.filter((_, i) => i !== idx);
    setForm({ ...form, input_schema: next });
  }

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
                {(t.default_priority ?? 0) !== 0 && (
                  <span className="text-xs bg-accent/10 text-accent px-1.5 py-0.5 rounded">
                    prio {t.default_priority}
                  </span>
                )}
              </div>
              <p className="text-sm text-muted">{t.description || "No description"}</p>
              {t.cron_expr && <p className="text-xs text-accent mt-1">Cron: {t.cron_expr}</p>}
              <p className="text-xs text-muted mt-1">Last run: {formatDate(t.last_run_at)}</p>
            </div>
            <div className="flex gap-1 ml-4 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => quickTrigger(t)} title="Run">
                <Play size={14} className="text-success" />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => openTrigger(t)} title="Run with params or batch">
                <Layers size={14} className="text-accent" />
              </Button>
              {t.workflow_type === "dag" && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => router.push(`/tasks/${t.id}/dag`)}
                  title="Open DAG editor"
                >
                  <Network size={14} className="text-accent" />
                </Button>
              )}
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
              <option value="dag">DAG (visual editor)</option>
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

          {form.workflow_type === "dag" && (
            <div className="rounded-md border border-border bg-background p-3">
              <p className="text-xs text-muted">
                Nodes and edges are authored in the visual editor.{" "}
                {editing
                  ? "Save first, then click the DAG icon on the task to open it."
                  : "Save the task first, then open the DAG editor from the task list."}
              </p>
            </div>
          )}

          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted">Cron expression (optional)</label>
              <Input
                value={form.cron_expr ?? ""}
                onChange={(e) => setForm({ ...form, cron_expr: e.target.value || null })}
                placeholder="*/5 * * * *"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted">Default priority</label>
              <Input
                type="number"
                value={form.default_priority ?? 0}
                onChange={(e) => setForm({ ...form, default_priority: Number(e.target.value) || 0 })}
                placeholder="0"
              />
              <p className="text-xs text-muted mt-1">Higher runs sooner. Default 0.</p>
            </div>
          </div>

          {/* Input schema editor */}
          <div>
            <div className="flex items-center justify-between">
              <label className="text-xs font-medium text-muted">Input schema</label>
              <Button variant="ghost" size="sm" onClick={addSchemaField}>
                <Plus size={12} className="mr-1" /> Add field
              </Button>
            </div>
            <p className="text-xs text-muted mb-2">
              Declare runtime params so the trigger UI renders proper form fields instead of raw JSON.
            </p>
            {schema.length === 0 && (
              <p className="text-xs text-muted italic">No fields. Trigger will fall back to a JSON textarea.</p>
            )}
            <div className="space-y-2">
              {schema.map((f, idx) => (
                <div key={idx} className="border border-border rounded p-2 space-y-2">
                  <div className="grid grid-cols-12 gap-2">
                    <Input
                      className="col-span-4"
                      placeholder="name (e.g. topic)"
                      value={f.name}
                      onChange={(e) => setSchemaField(idx, { name: e.target.value })}
                    />
                    <Select
                      className="col-span-3"
                      value={f.type}
                      onChange={(e) => setSchemaField(idx, { type: e.target.value as InputFieldType })}
                    >
                      {FIELD_TYPES.map((t) => (
                        <option key={t} value={t}>{t}</option>
                      ))}
                    </Select>
                    <label className="col-span-3 flex items-center gap-1.5 text-xs">
                      <input
                        type="checkbox"
                        checked={f.required ?? false}
                        onChange={(e) => setSchemaField(idx, { required: e.target.checked })}
                      />
                      required
                    </label>
                    <Button variant="ghost" size="sm" onClick={() => removeSchemaField(idx)} className="col-span-2">
                      <Trash2 size={12} className="text-danger" />
                    </Button>
                  </div>
                  <Input
                    placeholder="label (display name, optional)"
                    value={f.label ?? ""}
                    onChange={(e) => setSchemaField(idx, { label: e.target.value || undefined })}
                  />
                  <Input
                    placeholder="description / help text (optional)"
                    value={f.description ?? ""}
                    onChange={(e) => setSchemaField(idx, { description: e.target.value || undefined })}
                  />
                </div>
              ))}
            </div>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSubmit} disabled={!form.name || create.isPending || update.isPending}>
              {editing ? "Save" : "Create"}
            </Button>
          </div>
        </div>
      </Modal>

      {/* Trigger modal — schema-driven single run + batch */}
      <Modal
        open={triggerModalOpen}
        onClose={() => setTriggerModalOpen(false)}
        title={triggerTask ? `Run ${triggerTask.name}` : "Run task"}
      >
        <div className="space-y-3">
          <div className="flex gap-2">
            <Button
              variant={triggerMode === "single" ? "primary" : "secondary"}
              size="sm"
              onClick={() => setTriggerMode("single")}
            >
              Single
            </Button>
            <Button
              variant={triggerMode === "batch" ? "primary" : "secondary"}
              size="sm"
              onClick={() => setTriggerMode("batch")}
            >
              Batch
            </Button>
          </div>

          {triggerMode === "single" && (
            <>
              {triggerSchema.length > 0 ? (
                <div className="space-y-2">
                  {triggerSchema.map((field) => (
                    <FieldRow
                      key={field.name}
                      field={field}
                      value={triggerValues[field.name]}
                      onChange={(v) => setTriggerValues({ ...triggerValues, [field.name]: v })}
                    />
                  ))}
                </div>
              ) : (
                <div>
                  <label className="text-xs font-medium text-muted">
                    Runtime parameters (JSON, merged with task defaults)
                  </label>
                  <Textarea
                    rows={5}
                    value={triggerJson}
                    onChange={(e) => setTriggerJson(e.target.value)}
                    placeholder={'{\n  "topic": "multi-agent LLM frameworks",\n  "max_papers": 5\n}'}
                    className="font-mono text-xs"
                  />
                </div>
              )}
              <div>
                <label className="text-xs font-medium text-muted">
                  Priority (optional, overrides task default
                  {triggerTask ? ` of ${triggerTask.default_priority ?? 0}` : ""})
                </label>
                <Input
                  type="number"
                  value={triggerPriority}
                  onChange={(e) => setTriggerPriority(e.target.value)}
                  placeholder={String(triggerTask?.default_priority ?? 0)}
                />
              </div>
              <div className="flex justify-end gap-2 pt-1">
                <Button variant="secondary" onClick={() => setTriggerModalOpen(false)}>Cancel</Button>
                <Button onClick={handleSingleTrigger} disabled={trigger.isPending}>
                  <Play size={14} className="mr-1.5" /> Queue run
                </Button>
              </div>
            </>
          )}

          {triggerMode === "batch" && (
            <>
              {triggerSchema.length > 0 ? (
                <>
                  <p className="text-xs text-muted">
                    Each item below queues one run, executed in array order. Higher priority runs first.
                  </p>
                  <div className="space-y-3 max-h-[50vh] overflow-y-auto pr-1">
                    {batchItems.map((item, idx) => (
                      <div key={idx} className="border border-border rounded-md p-3 space-y-2 bg-background/50">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-semibold text-muted">Run #{idx + 1}</span>
                          <div className="flex gap-1">
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => addBatchItem(idx)}
                              title="Duplicate this item"
                            >
                              <Copy size={12} />
                            </Button>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => removeBatchItem(idx)}
                              disabled={batchItems.length === 1}
                              title="Remove"
                            >
                              <Trash2 size={12} className="text-danger" />
                            </Button>
                          </div>
                        </div>
                        {triggerSchema.map((field) => (
                          <FieldRow
                            key={field.name}
                            field={field}
                            value={item.values[field.name]}
                            onChange={(v) => setBatchItemValue(idx, field.name, v)}
                          />
                        ))}
                        <div>
                          <label className="text-xs font-medium text-muted">
                            Priority (blank = task default
                            {triggerTask ? ` ${triggerTask.default_priority ?? 0}` : ""})
                          </label>
                          <Input
                            type="number"
                            value={item.priority}
                            onChange={(e) => setBatchItemPriority(idx, e.target.value)}
                            placeholder={String(triggerTask?.default_priority ?? 0)}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                  <Button variant="secondary" size="sm" onClick={() => addBatchItem()}>
                    <Plus size={12} className="mr-1" /> Add item
                  </Button>
                </>
              ) : (
                <div>
                  <label className="text-xs font-medium text-muted">
                    Batch — JSON array of param sets, executed in order
                  </label>
                  <Textarea
                    rows={9}
                    value={batchJson}
                    onChange={(e) => setBatchJson(e.target.value)}
                    placeholder={
                      '[\n  {"topic": "diffusion models"},\n  {"topic": "rlhf", "priority": 5},\n  {"params": {"topic": "agents"}, "priority": 1}\n]'
                    }
                    className="font-mono text-xs"
                  />
                  <p className="text-xs text-muted mt-1">
                    Each item can be a bare params object, or
                    <code className="bg-background px-1 rounded">{"{params, priority}"}</code>.
                    Define an input_schema on the task to get a fielded UI here.
                  </p>
                </div>
              )}
              <div className="flex items-center justify-between pt-1">
                <span className="text-xs text-muted">
                  {triggerSchema.length > 0
                    ? `${batchItems.length} run${batchItems.length === 1 ? "" : "s"} queued`
                    : ""}
                </span>
                <div className="flex gap-2">
                  <Button variant="secondary" onClick={() => setTriggerModalOpen(false)}>Cancel</Button>
                  <Button onClick={handleBatchTrigger} disabled={triggerBatch.isPending}>
                    <Layers size={14} className="mr-1.5" /> Queue batch
                  </Button>
                </div>
              </div>
            </>
          )}
        </div>
      </Modal>
    </>
  );
}

// ── Schema-driven field renderer ────────────────────────────────────────────

function FieldRow({
  field,
  value,
  onChange,
}: {
  field: InputField;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  const label = field.label ?? field.name;
  return (
    <div>
      <label className="text-xs font-medium text-muted">
        {label}
        {field.required && <span className="text-danger ml-1">*</span>}
        <span className="text-muted/60 ml-1">({field.type})</span>
      </label>
      {renderInput(field, value, onChange)}
      {field.description && (
        <p className="text-xs text-muted mt-0.5">{field.description}</p>
      )}
    </div>
  );
}

function renderInput(
  field: InputField,
  value: unknown,
  onChange: (v: unknown) => void,
) {
  if (field.type === "boolean") {
    return (
      <label className="flex items-center gap-2 mt-1">
        <input
          type="checkbox"
          checked={Boolean(value)}
          onChange={(e) => onChange(e.target.checked)}
        />
        <span className="text-sm">{value ? "true" : "false"}</span>
      </label>
    );
  }
  if (field.type === "number") {
    return (
      <Input
        type="number"
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => {
          const v = e.target.value;
          onChange(v === "" ? undefined : Number(v));
        }}
      />
    );
  }
  if (field.type === "json") {
    const display =
      typeof value === "string"
        ? value
        : value === undefined
          ? ""
          : JSON.stringify(value, null, 2);
    return (
      <Textarea
        rows={4}
        className="font-mono text-xs"
        value={display}
        onChange={(e) => onChange(e.target.value)}
        placeholder='{"key": "value"}'
      />
    );
  }
  // string
  if (field.options && field.options.length > 0) {
    return (
      <Select
        value={value === undefined || value === null ? "" : String(value)}
        onChange={(e) => onChange(e.target.value || undefined)}
      >
        {!field.required && <option value="">— select —</option>}
        {field.options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </Select>
    );
  }
  return (
    <Input
      value={value === undefined || value === null ? "" : String(value)}
      onChange={(e) => onChange(e.target.value === "" ? undefined : e.target.value)}
    />
  );
}
