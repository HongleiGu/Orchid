"use client";

import { useRef, useState } from "react";
import toast from "react-hot-toast";
import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle, Download, Eye, EyeOff, Save, Upload, XCircle } from "lucide-react";
import { Badge, Button, Card, Input } from "@/components/ui";
import { useModels, useProviders, useSecrets, useUpdateSecrets } from "@/lib/hooks";
import { api } from "@/lib/api";

const KEY_LABELS: Record<string, string> = {
  ANTHROPIC_API_KEY: "Anthropic API Key",
  OPENAI_API_KEY: "OpenAI API Key",
  OPENAI_API_BASE: "OpenAI Base URL (optional)",
  GROQ_API_KEY: "Groq API Key",
  OPENROUTER_API_KEY: "OpenRouter API Key",
  TAVILY_API_KEY: "Tavily API Key (web search)",
  SERPAPI_API_KEY: "SerpAPI Key",
  BRAVE_API_KEY: "Brave Search Key",
  WECHAT_APP_ID: "WeChat Official Account App ID",
  WECHAT_APP_SECRET: "WeChat Official Account App Secret",
  GMAIL_CLIENT_ID: "Gmail OAuth Client ID",
  GMAIL_CLIENT_SECRET: "Gmail OAuth Client Secret",
  SEMANTIC_SCHOLAR_API_KEY: "Semantic Scholar API Key",
  OPENALEX_API_KEY: "OpenAlex API Key",
  LLM_DEFAULT_MODEL: "Default LLM Model",
};

export default function SettingsPage() {
  const providers = useProviders();
  const models = useModels();
  const secrets = useSecrets();
  const updateSecrets = useUpdateSecrets();

  // Track which fields the user has edited (key → new value)
  const [edits, setEdits] = useState<Record<string, string>>({});
  // Track which fields are showing the input (vs masked display)
  const [editing, setEditing] = useState<Set<string>>(new Set());

  function toggleEdit(key: string) {
    setEditing((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
        // discard unsaved change
        setEdits((e) => {
          const copy = { ...e };
          delete copy[key];
          return copy;
        });
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function handleChange(key: string, value: string) {
    setEdits((prev) => ({ ...prev, [key]: value }));
  }

  async function handleSave() {
    const updates = Object.entries(edits)
      .filter(([, v]) => v !== undefined)
      .map(([key, value]) => ({ key, value }));

    if (updates.length === 0) {
      toast("Nothing to save");
      return;
    }

    try {
      await updateSecrets.mutateAsync(updates);
      toast.success("Secrets updated — restart backend to apply LLM key changes");
      setEdits({});
      setEditing(new Set());
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed to save");
    }
  }

  const hasEdits = Object.keys(edits).length > 0;

  return (
    <>
      <h1 className="text-2xl font-bold mb-6">Settings</h1>

      {/* Secrets / API Keys */}
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold">API Keys & Configuration</h2>
        {hasEdits && (
          <Button size="sm" onClick={handleSave} disabled={updateSecrets.isPending}>
            <Save size={14} className="mr-1.5" />
            Save changes
          </Button>
        )}
      </div>
      <Card className="mb-8">
        <div className="space-y-3">
          {secrets.data?.data.map((s) => {
            const isEditing = editing.has(s.key);
            const editValue = edits[s.key];
            return (
              <div key={s.key} className="flex items-center gap-3">
                <div className="w-52 shrink-0">
                  <label className="text-sm font-medium">{KEY_LABELS[s.key] ?? s.key}</label>
                  <p className="text-xs text-muted">{s.key}</p>
                </div>
                <div className="flex-1">
                  {isEditing ? (
                    <Input
                      type="text"
                      value={editValue ?? ""}
                      onChange={(e) => handleChange(s.key, e.target.value)}
                      placeholder={s.masked || "Enter value…"}
                    />
                  ) : (
                    <div className="flex items-center gap-2 h-9 px-3 rounded-md border border-border bg-background text-sm">
                      {s.is_set ? (
                        <span className="font-mono text-xs text-muted">{s.masked}</span>
                      ) : (
                        <span className="text-muted text-xs">Not set</span>
                      )}
                    </div>
                  )}
                </div>
                <div className="flex items-center gap-1.5 shrink-0">
                  {s.is_set ? (
                    <CheckCircle size={14} className="text-success" />
                  ) : (
                    <XCircle size={14} className="text-muted" />
                  )}
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={() => toggleEdit(s.key)}
                    title={isEditing ? "Cancel" : "Edit"}
                  >
                    {isEditing ? <EyeOff size={14} /> : <Eye size={14} />}
                  </Button>
                </div>
              </div>
            );
          })}
          {secrets.isLoading && <p className="text-sm text-muted">Loading…</p>}
        </div>
      </Card>

      {/* Import / Export */}
      <ImportExport />

      {/* Providers */}
      <h2 className="font-semibold mb-3">Providers</h2>
      <div className="grid gap-2 mb-8">
        {providers.data?.data.map((p) => (
          <Card key={p.name} className="flex items-center justify-between">
            <div>
              <span className="font-medium">{p.name}</span>
              <span className="text-xs text-muted ml-2">{p.base_url}</span>
            </div>
            <div className="flex items-center gap-2">
              {p.key_set ? (
                <span className="flex items-center gap-1 text-xs text-success">
                  <CheckCircle size={14} /> Key set
                </span>
              ) : (
                <span className="flex items-center gap-1 text-xs text-muted">
                  <XCircle size={14} /> No key
                </span>
              )}
            </div>
          </Card>
        ))}
        {providers.isLoading && <p className="text-sm text-muted">Loading…</p>}
      </div>

      {/* Models */}
      <h2 className="font-semibold mb-3">Available Models</h2>
      <Card>
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-left text-xs text-muted">
              <th className="pb-2">Model ID</th>
              <th className="pb-2">Provider</th>
              <th className="pb-2">Tools</th>
              <th className="pb-2">Vision</th>
              <th className="pb-2">Context</th>
            </tr>
          </thead>
          <tbody>
            {models.data?.data.map((m) => (
              <tr key={m.id} className="border-b border-border last:border-0">
                <td className="py-2 font-mono text-xs">{m.id}</td>
                <td className="py-2"><Badge value={m.provider} /></td>
                <td className="py-2">{m.tools ? "yes" : "—"}</td>
                <td className="py-2">{m.vision ? "yes" : "—"}</td>
                <td className="py-2">{(m.context / 1000).toFixed(0)}k</td>
              </tr>
            ))}
          </tbody>
        </table>
        {models.isLoading && <p className="text-sm text-muted py-4">Loading…</p>}
      </Card>
    </>
  );
}

// ── Import / Export component ────────────────────────────────────────────────

function ImportExport() {
  const qc = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [importing, setImporting] = useState(false);

  function download(data: unknown, filename: string) {
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleExport(mode: "all" | "agents" | "tasks") {
    try {
      let res;
      if (mode === "agents") res = await api.config.exportAgents();
      else if (mode === "tasks") res = await api.config.exportTasks();
      else res = await api.config.export();

      const filename = mode === "all" ? "pipeline-config.json"
        : mode === "agents" ? "agents-config.json" : "tasks-config.json";

      // For agents/tasks-only export, wrap in the standard format
      const payload = mode === "agents" ? { agents: res.data }
        : mode === "tasks" ? { tasks: res.data }
        : res.data;

      download(payload, filename);
      toast.success(`Exported ${filename}`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Export failed");
    }
  }

  async function handleImport(file: File) {
    setImporting(true);
    try {
      const text = await file.text();
      const data = JSON.parse(text);
      const res = await api.config.import(data);
      const r = res.data;

      const parts: string[] = [];
      if (r.skills_installed) parts.push(`${r.skills_installed} skills installed`);
      if (r.skills_skipped) parts.push(`${r.skills_skipped} skills skipped`);
      if (r.agents_created) parts.push(`${r.agents_created} agents created`);
      if (r.agents_skipped) parts.push(`${r.agents_skipped} agents skipped`);
      if (r.tasks_created) parts.push(`${r.tasks_created} tasks created`);
      if (r.tasks_skipped) parts.push(`${r.tasks_skipped} tasks skipped`);

      if (r.errors.length > 0) {
        toast.error(`Import done with errors:\n${r.errors.join("\n")}`);
      } else {
        toast.success(parts.join(", ") || "Nothing to import");
      }

      qc.invalidateQueries({ queryKey: ["agents"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Import failed — check JSON format");
    } finally {
      setImporting(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  return (
    <>
      <h2 className="font-semibold mb-3">Pipeline Config</h2>
      <Card className="mb-8">
        <div className="flex flex-wrap gap-3 items-center">
          <div className="flex gap-2">
            <Button variant="secondary" size="sm" onClick={() => handleExport("all")}>
              <Download size={14} className="mr-1.5" /> Export all
            </Button>
            <Button variant="ghost" size="sm" onClick={() => handleExport("agents")}>
              Export agents
            </Button>
            <Button variant="ghost" size="sm" onClick={() => handleExport("tasks")}>
              Export tasks
            </Button>
          </div>
          <div className="border-l border-border h-6" />
          <div>
            <input
              ref={fileRef}
              type="file"
              accept=".json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0];
                if (file) handleImport(file);
              }}
            />
            <Button
              variant="primary"
              size="sm"
              disabled={importing}
              onClick={() => fileRef.current?.click()}
            >
              <Upload size={14} className="mr-1.5" />
              {importing ? "Importing…" : "Import config"}
            </Button>
          </div>
        </div>
        <p className="text-xs text-muted mt-3">
          Export/import agents and tasks as JSON. Agent names are used as references — configs are portable across instances.
        </p>
      </Card>
    </>
  );
}
