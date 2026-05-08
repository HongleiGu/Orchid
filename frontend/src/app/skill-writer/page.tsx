"use client";

import { useMemo, useState } from "react";
import type { ReactNode } from "react";
import { Check, FileText, Loader2, Save, Wrench } from "lucide-react";
import { Badge, Button, Card, Input, Select, Textarea } from "@/components/ui";
import { useDraftSkill, useSaveSkillDraft } from "@/lib/hooks";

export default function SkillWriterPage() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [selectedFile, setSelectedFile] = useState("README.md");
  const draftSkill = useDraftSkill();
  const saveDraft = useSaveSkillDraft();

  const draft = draftSkill.data?.data;
  const file = useMemo(() => {
    if (!draft) return null;
    return draft.files.find((item) => item.path === selectedFile) ?? draft.files[0] ?? null;
  }, [draft, selectedFile]);

  function onDraft() {
    const trimmed = description.trim();
    if (!trimmed || draftSkill.isPending) return;
    draftSkill.mutate(
      { description: trimmed, name: name.trim() || undefined },
      {
        onSuccess: (res) => {
          const files = res.data.files;
          setSelectedFile(files.find((item) => item.path === "README.md")?.path ?? files[0]?.path ?? "");
        },
      }
    );
  }

  function onSave() {
    if (!draft || saveDraft.isPending) return;
    saveDraft.mutate(draft);
  }

  return (
    <main className="h-full overflow-auto">
      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Skill Writer</h1>
            <p className="text-sm text-muted mt-1">
              Draft external Orchid skills with documented setup, env vars, and install notes.
            </p>
          </div>
          <div className="flex gap-2">
            <Button onClick={onDraft} disabled={!description.trim() || draftSkill.isPending}>
              {draftSkill.isPending ? <Loader2 size={16} className="mr-2 animate-spin" /> : <Wrench size={16} className="mr-2" />}
              Draft
            </Button>
            <Button variant="secondary" onClick={onSave} disabled={!draft || saveDraft.isPending}>
              {saveDraft.isPending ? <Loader2 size={16} className="mr-2 animate-spin" /> : <Save size={16} className="mr-2" />}
              Save
            </Button>
          </div>
        </div>

        <section className="grid grid-cols-1 xl:grid-cols-[minmax(0,0.9fr)_minmax(0,1.1fr)] gap-5">
          <Card className="space-y-4">
            <div>
              <label className="text-xs font-medium text-muted">Name</label>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="linear issue search"
                className="mt-1"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted">Skill Request</label>
              <Textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Create a skill that searches Linear issues by query and returns issue id, title, status, assignee, and URL. It should use LINEAR_API_KEY from the environment."
                className="mt-1 min-h-[260px]"
              />
            </div>
            {draftSkill.error ? (
              <Status tone="error" text={(draftSkill.error as Error).message} />
            ) : null}
            {saveDraft.error ? (
              <Status tone="error" text={(saveDraft.error as Error).message} />
            ) : null}
            {saveDraft.data ? (
              <Status
                tone={saveDraft.data.data.valid ? "success" : "warning"}
                text={
                  saveDraft.data.data.valid
                    ? `Saved to ${saveDraft.data.data.directory}. Install target: ${saveDraft.data.data.install_target}`
                    : `Saved, but validation failed: ${saveDraft.data.data.validation_error}`
                }
              />
            ) : null}
          </Card>

          <div className="space-y-5">
            <Card className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-sm font-semibold">Draft Review</h2>
                  {draft ? <p className="text-xs text-muted mt-1">{draft.package_name} / {draft.skill_name}</p> : null}
                </div>
                {draft ? <Badge value={`${draft.files.length} files`} /> : null}
              </div>

              {draft ? (
                <div className="space-y-4">
                  {draft.summary ? <p className="text-sm text-muted">{draft.summary}</p> : null}
                  <Section title="Environment">
                    {draft.env_vars.length ? (
                      <div className="space-y-2">
                        {draft.env_vars.map((env) => (
                          <div key={env.name} className="rounded-md border border-border px-3 py-2 text-sm">
                            <div className="flex items-center gap-2">
                              <span className="font-mono font-medium">{env.name}</span>
                              <Badge value={env.required ? "required" : "optional"} />
                            </div>
                            {env.description ? <p className="text-muted mt-1">{env.description}</p> : null}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="text-sm text-muted">No env vars required.</p>
                    )}
                  </Section>

                  <ListSection title="Questions" items={draft.questions} tone="warning" />
                  <ListSection title="Install Notes" items={draft.install_notes} />
                  <ListSection title="Test Plan" items={draft.test_plan} />
                  <ListSection title="Limitations" items={draft.limitations} />
                </div>
              ) : (
                <div className="text-sm text-muted py-10 text-center">
                  Drafted skill details will appear here.
                </div>
              )}
            </Card>

            <Card>
              <div className="flex items-center justify-between gap-3 mb-3">
                <h2 className="text-sm font-semibold">Files</h2>
                {draft?.files.length ? (
                  <Select value={file?.path ?? ""} onChange={(event) => setSelectedFile(event.target.value)} className="max-w-xs">
                    {draft.files.map((item) => (
                      <option key={item.path} value={item.path}>{item.path}</option>
                    ))}
                  </Select>
                ) : null}
              </div>
              <div className="flex items-center gap-2 text-xs text-muted mb-2">
                <FileText size={14} />
                <span>{file?.path ?? "No file selected"}</span>
              </div>
              <pre className="min-h-[320px] max-h-[560px] overflow-auto rounded-md border border-border bg-background p-3 text-xs leading-relaxed">
                {file?.content ?? "No draft yet."}
              </pre>
            </Card>
          </div>
        </section>
      </div>
    </main>
  );
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium uppercase text-muted">{title}</h3>
      {children}
    </div>
  );
}

function ListSection({ title, items, tone }: { title: string; items: string[]; tone?: "warning" }) {
  if (!items.length) return null;
  return (
    <Section title={title}>
      <ul className="list-disc pl-5 text-sm space-y-1">
        {items.map((item, index) => (
          <li key={`${title}-${index}`} className={tone === "warning" ? "text-yellow-800" : ""}>
            {item}
          </li>
        ))}
      </ul>
    </Section>
  );
}

function Status({ tone, text }: { tone: "error" | "success" | "warning"; text: string }) {
  const classes = {
    error: "border-red-200 bg-red-50 text-red-700",
    success: "border-green-200 bg-green-50 text-green-700",
    warning: "border-yellow-200 bg-yellow-50 text-yellow-800",
  };
  return (
    <div className={`rounded-md border px-3 py-2 text-sm ${classes[tone]}`}>
      {tone === "success" ? <Check size={14} className="inline mr-1" /> : null}
      {text}
    </div>
  );
}
