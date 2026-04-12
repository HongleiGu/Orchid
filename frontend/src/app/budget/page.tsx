"use client";

import { useState } from "react";
import toast from "react-hot-toast";
import { useQuery, useQueryClient, useMutation } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { Badge, Button, Card, Empty, Input, Modal, Select } from "@/components/ui";
import { api } from "@/lib/api";

export default function BudgetPage() {
  const [days, setDays] = useState(30);

  const usage = useQuery({
    queryKey: ["budget", "usage", days],
    queryFn: () => api.budget.usage(days),
  });
  const byModel = useQuery({
    queryKey: ["budget", "by-model", days],
    queryFn: () => api.budget.byModel(days),
  });
  const byAgent = useQuery({
    queryKey: ["budget", "by-agent", days],
    queryFn: () => api.budget.byAgent(days),
  });

  const u = usage.data?.data;

  return (
    <>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold">Budget & Usage</h1>
        <Select
          className="w-40"
          value={days}
          onChange={(e) => setDays(Number(e.target.value))}
        >
          <option value={1}>Last 24h</option>
          <option value={7}>Last 7 days</option>
          <option value={30}>Last 30 days</option>
          <option value={90}>Last 90 days</option>
        </Select>
      </div>

      {/* Summary cards */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <StatCard label="Total cost" value={u ? `$${u.cost_usd.toFixed(4)}` : "—"} />
        <StatCard label="Total tokens" value={u ? u.total_tokens.toLocaleString() : "—"} />
        <StatCard label="LLM calls" value={u ? u.llm_calls.toLocaleString() : "—"} />
        <StatCard
          label="Avg cost/call"
          value={u && u.llm_calls > 0 ? `$${(u.cost_usd / u.llm_calls).toFixed(4)}` : "—"}
        />
      </div>

      {/* Usage by model */}
      <h2 className="font-semibold mb-3">By Model</h2>
      <Card className="mb-6">
        {byModel.data?.data.length === 0 && <Empty message="No usage data yet." />}
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th className="pb-2">Model</th>
              <th className="pb-2 text-right">Calls</th>
              <th className="pb-2 text-right">Input tokens</th>
              <th className="pb-2 text-right">Output tokens</th>
              <th className="pb-2 text-right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {byModel.data?.data.map((m) => (
              <tr key={m.model} className="border-b border-border last:border-0">
                <td className="py-2 font-mono text-xs">{m.model}</td>
                <td className="py-2 text-right">{m.calls}</td>
                <td className="py-2 text-right">{m.input_tokens.toLocaleString()}</td>
                <td className="py-2 text-right">{m.output_tokens.toLocaleString()}</td>
                <td className="py-2 text-right font-medium">${m.cost_usd.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Usage by agent */}
      <h2 className="font-semibold mb-3">By Agent</h2>
      <Card className="mb-6">
        {byAgent.data?.data.length === 0 && <Empty message="No usage data yet." />}
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th className="pb-2">Agent</th>
              <th className="pb-2 text-right">Calls</th>
              <th className="pb-2 text-right">Input tokens</th>
              <th className="pb-2 text-right">Output tokens</th>
              <th className="pb-2 text-right">Cost</th>
            </tr>
          </thead>
          <tbody>
            {byAgent.data?.data.map((a) => (
              <tr key={a.agent} className="border-b border-border last:border-0">
                <td className="py-2 font-medium">{a.agent}</td>
                <td className="py-2 text-right">{a.calls}</td>
                <td className="py-2 text-right">{a.input_tokens.toLocaleString()}</td>
                <td className="py-2 text-right">{a.output_tokens.toLocaleString()}</td>
                <td className="py-2 text-right font-medium">${a.cost_usd.toFixed(4)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      {/* Budget limits */}
      <BudgetLimits />
    </>
  );
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <Card>
      <p className="text-xs text-muted">{label}</p>
      <p className="text-xl font-bold mt-1">{value}</p>
    </Card>
  );
}

function BudgetLimits() {
  const qc = useQueryClient();
  const [modalOpen, setModalOpen] = useState(false);
  const [form, setForm] = useState({
    scope_type: "global",
    scope_id: "global",
    max_tokens_per_run: "",
    max_cost_per_run: "",
    max_cost_per_day: "",
    max_cost_per_month: "",
  });

  const limits = useQuery({
    queryKey: ["budget", "limits"],
    queryFn: () => api.budget.limits(),
  });

  const setLimit = useMutation({
    mutationFn: (body: Parameters<typeof api.budget.setLimit>[0]) =>
      api.budget.setLimit(body),
    onSuccess: () => {
      toast.success("Limit saved");
      qc.invalidateQueries({ queryKey: ["budget", "limits"] });
      setModalOpen(false);
    },
    onError: (e: Error) => toast.error(e.message),
  });

  const deleteLimit = useMutation({
    mutationFn: (id: string) => api.budget.deleteLimit(id),
    onSuccess: () => {
      toast.success("Limit removed");
      qc.invalidateQueries({ queryKey: ["budget", "limits"] });
    },
    onError: (e: Error) => toast.error(e.message),
  });

  function handleSubmit() {
    setLimit.mutate({
      scope_type: form.scope_type,
      scope_id: form.scope_type === "global" ? "global" : form.scope_id,
      max_tokens_per_run: form.max_tokens_per_run ? Number(form.max_tokens_per_run) : null,
      max_cost_per_run: form.max_cost_per_run ? Number(form.max_cost_per_run) : null,
      max_cost_per_day: form.max_cost_per_day ? Number(form.max_cost_per_day) : null,
      max_cost_per_month: form.max_cost_per_month ? Number(form.max_cost_per_month) : null,
    });
  }

  const SCOPE_LABELS: Record<string, string> = {
    global: "Global",
    agent: "Per Agent",
    task: "Per Task",
  };

  return (
    <>
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold">Budget Limits</h2>
        <Button size="sm" onClick={() => setModalOpen(true)}>
          <Plus size={14} className="mr-1.5" /> Add limit
        </Button>
      </div>

      {limits.data?.data.length === 0 && (
        <Card><Empty message="No budget limits set. Runs are unlimited." /></Card>
      )}

      <div className="grid gap-2 mb-6">
        {limits.data?.data.map((l) => (
          <Card key={l.id} className="flex items-center justify-between">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <Badge value={l.scope_type} />
                {l.scope_type !== "global" && (
                  <span className="font-mono text-xs text-muted">{l.scope_id.slice(0, 12)}…</span>
                )}
              </div>
              <div className="flex gap-4 text-xs text-muted">
                {l.max_tokens_per_run != null && <span>Max tokens/run: {l.max_tokens_per_run.toLocaleString()}</span>}
                {l.max_cost_per_run != null && <span>Max cost/run: ${l.max_cost_per_run}</span>}
                {l.max_cost_per_day != null && <span>Max cost/day: ${l.max_cost_per_day}</span>}
                {l.max_cost_per_month != null && <span>Max cost/month: ${l.max_cost_per_month}</span>}
              </div>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => {
                if (confirm("Remove this limit?")) deleteLimit.mutate(l.id);
              }}
            >
              <Trash2 size={14} className="text-danger" />
            </Button>
          </Card>
        ))}
      </div>

      <Modal open={modalOpen} onClose={() => setModalOpen(false)} title="Set Budget Limit">
        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium text-muted">Scope</label>
            <Select
              value={form.scope_type}
              onChange={(e) => setForm({ ...form, scope_type: e.target.value, scope_id: e.target.value === "global" ? "global" : "" })}
            >
              <option value="global">Global (all runs)</option>
              <option value="agent">Per Agent</option>
              <option value="task">Per Task</option>
            </Select>
          </div>
          {form.scope_type !== "global" && (
            <div>
              <label className="text-xs font-medium text-muted">{form.scope_type === "agent" ? "Agent" : "Task"} ID</label>
              <Input
                value={form.scope_id}
                onChange={(e) => setForm({ ...form, scope_id: e.target.value })}
                placeholder="Paste ID"
              />
            </div>
          )}
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-xs font-medium text-muted">Max tokens per run</label>
              <Input
                type="number"
                value={form.max_tokens_per_run}
                onChange={(e) => setForm({ ...form, max_tokens_per_run: e.target.value })}
                placeholder="e.g. 50000"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted">Max cost per run ($)</label>
              <Input
                type="number"
                step="0.01"
                value={form.max_cost_per_run}
                onChange={(e) => setForm({ ...form, max_cost_per_run: e.target.value })}
                placeholder="e.g. 0.50"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted">Max cost per day ($)</label>
              <Input
                type="number"
                step="0.01"
                value={form.max_cost_per_day}
                onChange={(e) => setForm({ ...form, max_cost_per_day: e.target.value })}
                placeholder="e.g. 5.00"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted">Max cost per month ($)</label>
              <Input
                type="number"
                step="0.01"
                value={form.max_cost_per_month}
                onChange={(e) => setForm({ ...form, max_cost_per_month: e.target.value })}
                placeholder="e.g. 50.00"
              />
            </div>
          </div>
          <div className="flex justify-end gap-2 pt-2">
            <Button variant="secondary" onClick={() => setModalOpen(false)}>Cancel</Button>
            <Button onClick={handleSubmit} disabled={setLimit.isPending}>Save</Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
