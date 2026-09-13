import { ForbiddenError, OrchidError, type Attestation, type Template, type TemplateInput } from "@orchid/client-core";
import { useMemo, useState } from "react";

import { errorMessage, useAsync, useRoute } from "../hooks";
import { useClient } from "../session";
import { Card, Empty, ErrorNote, Loading } from "../ui";

export function Templates({ path }: { path: string[] }) {
  return path[0] ? <TemplateDetail id={path[0]} /> : <TemplateList />;
}

function TemplateList() {
  const client = useClient();
  const [, navigate] = useRoute();
  const templates = useAsync(() => client.listTemplates(), [client]);

  if (templates.loading && !templates.data) return <Loading />;
  return (
    <div className="stack">
      <ErrorNote error={templates.error} onRetry={templates.reload} />
      {templates.data?.length === 0 && <Empty>No templates are installed on this server.</Empty>}
      {templates.data?.map((t) => (
        <button key={t.id} className="card card-button" onClick={() => navigate(`templates/${t.id}`)}>
          <div className="row between">
            <h2>{t.name}</h2>
            {t.requires.length > 0 && <span className="badge badge-locked">requires consent</span>}
          </div>
          <p className="muted clamp">{t.description}</p>
          <div className="list-sub">{t.category} · {t.inputs.length} inputs</div>
        </button>
      ))}
    </div>
  );
}

// ── detail ────────────────────────────────────────────────────────────────────

function TemplateDetail({ id }: { id: string }) {
  const client = useClient();
  const [, navigate] = useRoute();
  const template = useAsync(() => client.getTemplate(id), [client, id]);
  const attestations = useAsync(() => client.listAttestations(), [client]);

  if (template.loading && !template.data) return <Loading />;
  if (!template.data) return <ErrorNote error={template.error} onRetry={template.reload} />;
  const t = template.data;

  const required = t.requires
    .filter((r) => r.startsWith("attestation:"))
    .map((r) => r.slice("attestation:".length));
  const pending = required
    .map((aid) => attestations.data?.find((a) => a.id === aid))
    .filter((a): a is Attestation => !!a && !a.accepted);
  const unknownRequirements = t.requires.filter(
    (r) => !r.startsWith("attestation:") || (attestations.data && !attestations.data.some((a) => `attestation:${a.id}` === r)),
  );

  return (
    <div className="stack">
      <button className="link back" onClick={() => navigate("templates")}>← Templates</button>
      <Card title={t.name}>
        <p className="muted">{t.description}</p>
      </Card>

      {pending.map((a) => (
        <AttestationGate key={a.id} attestation={a} onAccepted={attestations.reload} />
      ))}
      {unknownRequirements.length > 0 && (
        <div className="note note-warn">
          This template requires {unknownRequirements.join(", ")}, which this console can't satisfy.
          The server will refuse to run it.
        </div>
      )}

      <RunForm
        template={t}
        locked={pending.length > 0 || unknownRequirements.length > 0}
        onStarted={(runId) => navigate(`runs/${runId}`)}
      />
    </div>
  );
}

function AttestationGate({ attestation: a, onAccepted }: { attestation: Attestation; onAccepted: () => void }) {
  const client = useClient();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const reconfirm = a.accepted_version !== null && a.accepted_version !== a.version;

  async function accept() {
    setBusy(true);
    setError(null);
    try {
      // The version echoed back is the one on screen: if the text changed since
      // it loaded, the server refuses rather than recording consent to wording
      // the user never saw.
      await client.acceptAttestation(a.id, a.version);
      onAccepted();
    } catch (err) {
      setError(err instanceof OrchidError && err.status === 409
        ? new Error("The wording changed while you were reading. Reload to see the current text.")
        : err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title={<span>🔒 {a.title}</span>}>
      <p>{reconfirm ? `The text was updated to version ${a.version}. Please read and confirm again.` : a.summary}</p>
      {!open ? (
        <button className="secondary" onClick={() => setOpen(true)}>Read full text</button>
      ) : (
        <>
          <div className="legal">{a.text}</div>
          <p className="list-sub">Version {a.version}{a.basis ? ` · ${a.basis}` : ""}</p>
          <ErrorNote error={error} />
          <button className="primary" onClick={accept} disabled={busy}>
            {busy ? "Recording…" : "I have read and accept this"}
          </button>
        </>
      )}
    </Card>
  );
}

// ── inputs ───────────────────────────────────────────────────────────────────

type Values = Record<string, string | boolean>;

function initialValue(input: TemplateInput): string | boolean {
  if (input.type === "boolean") return Boolean(input.default);
  if (input.default === null || input.default === undefined) return "";
  if (Array.isArray(input.default)) return input.default.join(", ");
  if (typeof input.default === "object") return JSON.stringify(input.default, null, 2);
  return String(input.default);
}

function coerce(input: TemplateInput, raw: string | boolean): unknown {
  if (input.type === "boolean") return Boolean(raw);
  const text = String(raw).trim();
  if (text === "") return undefined;
  switch (input.type) {
    case "number":
    case "integer": {
      const n = Number(text);
      if (Number.isNaN(n)) throw new Error(`${input.label || input.name} must be a number`);
      return input.type === "integer" ? Math.trunc(n) : n;
    }
    case "array":
    case "list":
      return text.split(/[,，\n]/).map((s) => s.trim()).filter(Boolean);
    case "object":
      try {
        return JSON.parse(text);
      } catch {
        throw new Error(`${input.label || input.name} must be valid JSON`);
      }
    default:
      return text;
  }
}

function RunForm({ template, locked, onStarted }: { template: Template; locked: boolean; onStarted: (runId: string) => void }) {
  const client = useClient();
  const initial = useMemo(
    () => Object.fromEntries(template.inputs.map((i) => [i.name, initialValue(i)])) as Values,
    [template],
  );
  const [values, setValues] = useState<Values>(initial);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [conflict, setConflict] = useState(false);

  async function start(force: boolean) {
    setBusy(true);
    setError(null);
    setConflict(false);
    try {
      const inputs: Record<string, unknown> = {};
      for (const input of template.inputs) {
        const v = coerce(input, values[input.name] ?? "");
        if (v !== undefined) inputs[input.name] = v;
      }
      const run = await client.runTemplate(template.id, { inputs, force });
      onStarted(run.run_id);
    } catch (err) {
      if (err instanceof OrchidError && err.status === 409) setConflict(true);
      else setError(err instanceof ForbiddenError ? new Error(`Not allowed: ${errorMessage(err)}`) : err);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card title="Run">
      <div className="stack">
        {template.inputs.map((input) => (
          <InputField
            key={input.name}
            input={input}
            value={values[input.name] ?? ""}
            onChange={(v) => setValues((prev) => ({ ...prev, [input.name]: v }))}
          />
        ))}
        <ErrorNote error={error} />
        {conflict && (
          <div className="note note-warn">
            A run of this template is already pending or running.
            <button className="link" onClick={() => start(true)} disabled={busy}>Start another anyway</button>
          </div>
        )}
        <button className="primary" disabled={busy || locked} onClick={() => start(false)}>
          {locked ? "Accept the requirement above first" : busy ? "Starting…" : "Start run"}
        </button>
      </div>
    </Card>
  );
}

function InputField({ input, value, onChange }: {
  input: TemplateInput; value: string | boolean; onChange: (v: string | boolean) => void;
}) {
  const label = input.label || input.name;
  if (input.type === "boolean") {
    return (
      <label className="check">
        <input type="checkbox" checked={Boolean(value)} onChange={(e) => onChange(e.target.checked)} />
        <span>{label}{input.description && <small className="muted"> — {input.description}</small>}</span>
      </label>
    );
  }
  const multiline = input.type === "object" || input.type === "array" || input.type === "list";
  return (
    <label className="field">
      <span>{label}{input.required && " *"}</span>
      {multiline ? (
        <textarea rows={input.type === "object" ? 5 : 2} value={String(value)} onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input
          type={input.type === "number" || input.type === "integer" ? "number" : "text"}
          value={String(value)} onChange={(e) => onChange(e.target.value)}
        />
      )}
      {input.description && <small className="muted">{input.description}{multiline && input.type !== "object" ? " (comma-separated)" : ""}</small>}
    </label>
  );
}
