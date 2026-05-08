"use client";

import { useState } from "react";
import toast from "react-hot-toast";
import { useQuery } from "@tanstack/react-query";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { Badge, Button, Card, Empty, Input, Modal, Select, Textarea } from "@/components/ui";
import { useAgents, useCreateAgent, useDeleteAgent, useModels, useUpdateAgent } from "@/lib/hooks";
import { api } from "@/lib/api";
import { formatDate, truncate } from "@/lib/utils";
import type { Agent, AgentCreate } from "@/lib/types";

const BLANK: AgentCreate = {
  name: "",
  role: "assistant",
  system_prompt: "",
  model: null,
  reasoning: false,
  skills: [],
};

export default function AgentsPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useAgents(page);
  const models = useModels();
  const registry = useQuery({
    queryKey: ["registry"],
    queryFn: () => api.registry.all(),
    staleTime: 30_000,
  });

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Agent | null>(null);
  const [form, setForm] = useState<AgentCreate>(BLANK);

  const create = useCreateAgent();
  const update = useUpdateAgent();
  const del = useDeleteAgent();

  const availableSkills = registry.data?.data.filter((r) => r.type === "skill") ?? [];

  function openCreate() {
    setEditing(null);
    setForm(BLANK);
    setModalOpen(true);
  }

  function openEdit(a: Agent) {
    setEditing(a);
    setForm({
      name: a.name,
      role: a.role,
      system_prompt: a.system_prompt,
      model: a.model,
      tools: [],
      skills: mergeSkillNames(a.tools, a.skills),
      reasoning: a.reasoning,
    });
    setModalOpen(true);
  }

  async function handleSubmit() {
    try {
      if (editing) {
        await update.mutateAsync({ id: editing.id, body: form });
        toast.success("Agent updated");
      } else {
        await create.mutateAsync(form);
        toast.success("Agent created");
      }
      setModalOpen(false);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  async function handleDelete(id: string) {
    if (!confirm("Delete this agent?")) return;
    try {
      await del.mutateAsync(id);
      toast.success("Agent deleted");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  function toggleSkill(name: string) {
    const current = form.skills ?? [];
    const next = current.includes(name)
      ? current.filter((n) => n !== name)
      : [...current, name];
    setForm({ ...form, tools: [], skills: next });
  }

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Agents</h1>
        <Button onClick={openCreate} size="sm">
          <Plus size={16} className="mr-1.5" /> New agent
        </Button>
      </div>

      {isLoading && <p className="text-sm text-muted">Loading…</p>}
      {data && data.data.length === 0 && <Empty message="No agents yet." />}

      <div className="grid gap-3">
        {data?.data.map((a) => (
          <Card key={a.id} className="flex items-start justify-between">
            <div className="min-w-0 flex-1">
              <div className="flex items-center gap-2 mb-1">
                <span className="font-semibold">{a.name}</span>
                <Badge value={a.role} />
              </div>
              <p className="text-xs text-muted mb-1">{a.model ?? "default model"}</p>
              <p className="text-sm text-muted">{truncate(a.system_prompt, 120) || "No prompt"}</p>
              {mergeSkillNames(a.tools, a.skills).length > 0 && (
                <div className="flex flex-wrap gap-1 mt-2">
                  {mergeSkillNames(a.tools, a.skills).map((s) => (
                    <span key={s} className="text-xs bg-purple-100 text-purple-700 px-2 py-0.5 rounded">
                      {s}
                    </span>
                  ))}
                </div>
              )}
              <p className="text-xs text-muted mt-2">Created {formatDate(a.created_at)}</p>
            </div>
            <div className="flex gap-1 ml-4 shrink-0">
              <Button variant="ghost" size="sm" onClick={() => openEdit(a)}>
                <Pencil size={14} />
              </Button>
              <Button variant="ghost" size="sm" onClick={() => handleDelete(a.id)}>
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
      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title={editing ? "Edit Agent" : "New Agent"}>
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted">Name</label>
            <Input value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="e.g. researcher" />
          </div>
          <div>
            <label className="text-xs font-medium text-muted">Role</label>
            <Select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="assistant">Assistant</option>
              <option value="orchestrator">Orchestrator</option>
              <option value="worker">Worker</option>
            </Select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted">Model</label>
            <Select value={form.model ?? ""} onChange={(e) => setForm({ ...form, model: e.target.value || null })}>
              <option value="">Default</option>
              {models.data?.data.map((m) => (
                <option key={m.id} value={m.id}>{m.id}</option>
              ))}
            </Select>
          </div>
          <div>
            <label className="text-xs font-medium text-muted">System prompt</label>
            <Textarea
              rows={4}
              value={form.system_prompt}
              onChange={(e) => setForm({ ...form, system_prompt: e.target.value })}
              placeholder="You are a helpful assistant…"
            />
          </div>

          {/* Skills picker */}
          <div>
            <label className="text-xs font-medium text-muted">Skills</label>
            <div className="flex flex-wrap gap-1.5 mt-1 p-2 border border-border rounded-md min-h-[36px]">
              {availableSkills.map((s) => {
                const selected = form.skills?.includes(s.name);
                return (
                  <button
                    key={s.name}
                    type="button"
                    title={s.description}
                    onClick={() => toggleSkill(s.name)}
                    className={`text-xs px-2 py-1 rounded transition-colors ${
                      selected
                        ? "bg-purple-600 text-white"
                        : "bg-purple-100 text-purple-700 hover:bg-purple-200"
                    }`}
                  >
                    {selected ? "✓ " : "+ "}{s.name.replace("@orchid/", "")}
                    <span className="text-[10px] ml-1 opacity-60">{s.source}</span>
                  </button>
                );
              })}
              {availableSkills.length === 0 && (
                <span className="text-xs text-muted">No skills available</span>
              )}
            </div>
          </div>

          {/* Reasoning toggle */}
          <div className="flex items-center gap-3 pt-1">
            <label className="flex items-center gap-2 cursor-pointer">
              <input
                type="checkbox"
                checked={form.reasoning ?? false}
                onChange={(e) => setForm({ ...form, reasoning: e.target.checked })}
                className="rounded border-border"
              />
              <span className="text-sm font-medium">Extended thinking</span>
            </label>
            <span className="text-xs text-muted">
              Adds a reasoning pass before execution — slower but more accurate
            </span>
          </div>

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSubmit} disabled={!form.name || create.isPending || update.isPending}>
              {editing ? "Save" : "Create"}
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}

function mergeSkillNames(...groups: string[][]): string[] {
  const merged: string[] = [];
  for (const group of groups) {
    for (const name of group) {
      if (!merged.includes(name)) merged.push(name);
    }
  }
  return merged;
}
