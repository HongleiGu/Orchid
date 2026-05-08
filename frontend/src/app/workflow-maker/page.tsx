"use client";

import { useMemo, useState } from "react";
import { Check, Loader2, Sparkles } from "lucide-react";
import { Badge, Button, Card, Input, Textarea } from "@/components/ui";
import { useDraftWorkflow, useImportConfig } from "@/lib/hooks";

export default function WorkflowMakerPage() {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const draft = useDraftWorkflow();
  const importConfig = useImportConfig();

  const workflow = draft.data?.data.workflow;
  const draftJson = useMemo(
    () => (workflow ? JSON.stringify(workflow, null, 2) : ""),
    [workflow]
  );

  const onDraft = () => {
    const trimmed = description.trim();
    if (!trimmed || draft.isPending) return;
    draft.mutate({
      description: trimmed,
      name: name.trim() || undefined,
    });
  };

  const onImport = () => {
    if (!workflow || importConfig.isPending) return;
    importConfig.mutate(workflow);
  };

  return (
    <main className="h-full overflow-auto">
      <div className="max-w-6xl mx-auto px-6 py-6 space-y-6">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Workflow Maker</h1>
            <p className="text-sm text-muted mt-1">
              Turn a personal automation idea into an import-ready Orchid DAG.
            </p>
          </div>
          <Button onClick={onDraft} disabled={!description.trim() || draft.isPending}>
            {draft.isPending ? <Loader2 size={16} className="mr-2 animate-spin" /> : <Sparkles size={16} className="mr-2" />}
            Draft
          </Button>
        </div>

        <section className="grid grid-cols-1 xl:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)] gap-5">
          <Card className="space-y-4">
            <div>
              <label className="text-xs font-medium text-muted">Name</label>
              <Input
                value={name}
                onChange={(event) => setName(event.target.value)}
                placeholder="Weekly research digest"
                className="mt-1"
              />
            </div>
            <div>
              <label className="text-xs font-medium text-muted">Workflow Request</label>
              <Textarea
                value={description}
                onChange={(event) => setDescription(event.target.value)}
                placeholder="Collect recent arXiv papers about multi-agent planning, rank them by relevance, summarize the strongest themes, and save a markdown report to the vault."
                className="mt-1 min-h-[260px]"
              />
            </div>
            {draft.error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {(draft.error as Error).message}
              </div>
            ) : null}
            {importConfig.error ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                {(importConfig.error as Error).message}
              </div>
            ) : null}
            {importConfig.data ? (
              <div className="rounded-md border border-green-200 bg-green-50 px-3 py-2 text-sm text-green-700">
                Imported {importConfig.data.data.agents_created} agents and {importConfig.data.data.tasks_created} tasks.
              </div>
            ) : null}
          </Card>

          <div className="space-y-5">
            <Card className="space-y-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold">Draft Review</h2>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={onImport}
                  disabled={!workflow || importConfig.isPending}
                >
                  {importConfig.isPending ? <Loader2 size={14} className="mr-2 animate-spin" /> : <Check size={14} className="mr-2" />}
                  Import
                </Button>
              </div>

              {draft.data ? (
                <div className="space-y-4">
                  <div className="space-y-2">
                    <h3 className="text-xs font-medium uppercase text-muted">Plan</h3>
                    <ol className="list-decimal pl-5 text-sm space-y-1">
                      {draft.data.data.plan.map((step, index) => (
                        <li key={`${step}-${index}`}>{step}</li>
                      ))}
                    </ol>
                  </div>

                  <SkillSection
                    title="Required Skills"
                    skills={draft.data.data.required_skills}
                    missing={draft.data.data.missing_required_skills}
                  />
                  <SkillSection
                    title="Optional Skills"
                    skills={draft.data.data.optional_skills}
                    missing={draft.data.data.missing_optional_skills}
                  />

                  {draft.data.data.notes.length ? (
                    <div className="space-y-2">
                      <h3 className="text-xs font-medium uppercase text-muted">Notes</h3>
                      <ul className="list-disc pl-5 text-sm space-y-1">
                        {draft.data.data.notes.map((note, index) => (
                          <li key={`${note}-${index}`}>{note}</li>
                        ))}
                      </ul>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="text-sm text-muted py-10 text-center">
                  Drafted DAG details will appear here.
                </div>
              )}
            </Card>

            <Card>
              <div className="flex items-center justify-between gap-3 mb-3">
                <h2 className="text-sm font-semibold">Import JSON</h2>
                {workflow ? <Badge value={`${workflow.agents.length} agents`} /> : null}
              </div>
              <pre className="min-h-[260px] max-h-[520px] overflow-auto rounded-md border border-border bg-background p-3 text-xs leading-relaxed">
                {draftJson || "No draft yet."}
              </pre>
            </Card>
          </div>
        </section>
      </div>
    </main>
  );
}

function SkillSection({
  title,
  skills,
  missing,
}: {
  title: string;
  skills: string[];
  missing: { name: string; reason: string; alternative?: string | null }[];
}) {
  if (!skills.length && !missing.length) return null;

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium uppercase text-muted">{title}</h3>
      {skills.length ? (
        <div className="flex flex-wrap gap-2">
          {skills.map((skill) => (
            <Badge key={skill} value={skill} />
          ))}
        </div>
      ) : null}
      {missing.length ? (
        <div className="space-y-2">
          {missing.map((skill) => (
            <div key={skill.name} className="rounded-md border border-yellow-200 bg-yellow-50 px-3 py-2 text-sm text-yellow-800">
              <div className="font-medium">{skill.name}</div>
              {skill.reason ? <div>{skill.reason}</div> : null}
              {skill.alternative ? <div className="text-yellow-700">Fallback: {skill.alternative}</div> : null}
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
