import {
  ForbiddenError,
  TERMINAL_RUN_STATUSES,
  type RunDetail,
  type RunEvent,
  type SpanNode,
  type StreamState,
} from "@orchid/client-core";
import { useEffect, useMemo, useRef, useState } from "react";

import { fmtDuration, fmtTime, fmtTokens, fmtUsd } from "../format";
import { errorMessage, useAsync, useRoute } from "../hooks";
import { isAuthError, useClient, useSession } from "../session";
import { Card, Empty, ErrorNote, Loading, Stat, StatusBadge } from "../ui";

export function Runs({ path }: { path: string[] }) {
  return path[0] ? <RunView id={path[0]} /> : <RunList />;
}

const FILTERS = ["all", "running", "pending", "done", "failed", "cancelled"] as const;

function RunList() {
  const client = useClient();
  const [, navigate] = useRoute();
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>("all");
  const [page, setPage] = useState(1);
  const runs = useAsync(
    () => client.listRuns({ page, status: filter === "all" ? undefined : filter }),
    [client, filter, page],
    { pollMs: 10_000 },
  );
  const pages = runs.data ? Math.max(1, Math.ceil(runs.data.meta.total / runs.data.meta.page_size)) : 1;

  return (
    <div className="stack">
      <div className="chips" role="tablist">
        {FILTERS.map((f) => (
          <button key={f} role="tab" aria-selected={f === filter} className={`chip ${f === filter ? "chip-on" : ""}`}
            onClick={() => { setFilter(f); setPage(1); }}>
            {f}
          </button>
        ))}
      </div>

      <ErrorNote error={runs.error} onRetry={runs.reload} />
      {runs.loading && !runs.data ? <Loading /> : runs.data?.data.length ? (
        <ul className="list card">
          {runs.data.data.map((run) => (
            <li key={run.id}>
              <button className="list-item" onClick={() => navigate(`runs/${run.id}`)}>
                <div className="list-main">
                  <StatusBadge status={run.status} />
                  <span className="mono">{run.id.slice(-8)}</span>
                  <span className="grow" />
                  <span className="muted">{fmtUsd(run.cost.cost_usd)}</span>
                </div>
                <div className="list-sub">
                  {fmtTime(run.created_at)} · {fmtDuration(run.started_at, run.finished_at)}
                  {run.model_used ? ` · ${run.model_used}` : ""}
                </div>
              </button>
            </li>
          ))}
        </ul>
      ) : <Empty>No runs match.</Empty>}

      {pages > 1 && (
        <div className="row between">
          <button className="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Newer</button>
          <span className="muted">{page} / {pages}</span>
          <button className="secondary" disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Older</button>
        </div>
      )}
    </div>
  );
}

// ── detail ────────────────────────────────────────────────────────────────────

const MAX_RENDERED_EVENTS = 600;

// Ask for everything and let the server decide. A full deployment returns agent
// output and routing (debug-only by design); the run-only edition caps it at
// info, and the applied level comes back on the run so the UI can say so.
const REQUESTED_VERBOSITY = "debug";

function RunView({ id }: { id: string }) {
  const client = useClient();
  const { expire } = useSession();
  const [, navigate] = useRoute();
  const detail = useAsync(() => client.getRun(id, REQUESTED_VERBOSITY), [client, id]);
  const [live, setLive] = useState<RunEvent[]>([]);
  const [streamState, setStreamState] = useState<StreamState | null>(null);
  const [streamNote, setStreamNote] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [actionError, setActionError] = useState<unknown>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [follow, setFollow] = useState(true);

  const run = detail.data;
  const terminal = run ? TERMINAL_RUN_STATUSES.has(run.status) : false;

  // Follow a live run from where the snapshot ended, so nothing already shown
  // is replayed. A finished run is shown from its snapshot with no connection.
  useEffect(() => {
    if (!run || terminal) return;
    const lastSeq = run.events.reduce((max, e) => Math.max(max, e.seq), 0);
    setLive([]);
    const handle = client.streamRun(id, {
      verbosity: REQUESTED_VERBOSITY,
      lastEventId: lastSeq,
      onEvent: (event) => setLive((prev) => [...prev, event]),
      onState: (state, error) => {
        setStreamState(state);
        if (error && isAuthError(error)) expire();
        setStreamNote(state === "reconnecting" && error ? `Reconnecting — ${errorMessage(error)}` : state === "failed" && error ? errorMessage(error) : null);
      },
    });
    handle.done.then((outcome) => { if (outcome === "ended") detail.reload(); });
    return () => handle.close();
    // Re-subscribe only when the run identity or its terminal-ness changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [client, id, run?.id, terminal]);

  const events = useMemo(() => {
    const merged = [...(run?.events ?? []), ...live];
    const seen = new Set<number>();
    const unique = merged.filter((e) => (seen.has(e.seq) ? false : (seen.add(e.seq), true)));
    return unique.slice(-MAX_RENDERED_EVENTS);
  }, [run?.events, live]);

  useEffect(() => {
    if (follow) bottomRef.current?.scrollIntoView({ block: "end" });
  }, [events.length, follow]);

  async function cancel() {
    if (!confirm("Cancel this run? Work in progress is discarded.")) return;
    setCancelling(true);
    setActionError(null);
    try {
      await client.cancelRun(id);
      detail.reload();
    } catch (err) {
      setActionError(err);
    } finally {
      setCancelling(false);
    }
  }

  if (detail.loading && !run) return <Loading />;
  if (!run) return (
    <div className="stack">
      <button className="link back" onClick={() => navigate("runs")}>← Runs</button>
      <ErrorNote error={detail.error} onRetry={detail.reload} />
    </div>
  );

  const content = typeof run.result?.content === "string" ? run.result.content : null;

  return (
    <div className="stack">
      <button className="link back" onClick={() => navigate("runs")}>← Runs</button>

      <Card
        title={<span className="row"><StatusBadge status={run.status} /><span className="mono">{run.id}</span></span>}
        action={!terminal && (
          <button className="danger" onClick={cancel} disabled={cancelling}>{cancelling ? "Cancelling…" : "Cancel"}</button>
        )}
      >
        <div className="stats">
          <Stat label="cost" value={fmtUsd(run.cost.cost_usd)} />
          <Stat label="tokens" value={fmtTokens(run.cost.input_tokens + run.cost.output_tokens)} />
          <Stat label="LLM calls" value={run.cost.llm_calls} />
          <Stat label="duration" value={fmtDuration(run.started_at, run.finished_at)} />
        </div>
        <p className="list-sub">Created {fmtTime(run.created_at)}{run.model_used ? ` · ${run.model_used}` : ""}</p>
        {run.error && <div className="note note-error">{run.error}</div>}
        <ErrorNote error={actionError} />
      </Card>

      {content && (
        <Card title="Result">
          <div className="result">{content}</div>
        </Card>
      )}

      {terminal && <SpanCosts runId={id} run={run} />}

      <Card
        title={<span>Events <small className="muted">({events.length}{!terminal && streamState ? ` · ${streamState}` : ""})</small></span>}
        action={!terminal && (
          <label className="check small">
            <input type="checkbox" checked={follow} onChange={(e) => setFollow(e.target.checked)} />
            <span>follow</span>
          </label>
        )}
      >
        {streamNote && <div className="note note-warn">{streamNote}</div>}
        {run.verbosity !== REQUESTED_VERBOSITY && (
          <p className="list-sub">
            Showing “{run.verbosity}” detail — this edition withholds agent output and routing.
          </p>
        )}
        {events.length === 0 ? <Empty>No events yet.</Empty> : (
          <ol className="events">
            {events.map((e) => <EventRow key={e.seq} event={e} />)}
          </ol>
        )}
        <div ref={bottomRef} />
      </Card>
    </div>
  );
}

function summarize(e: RunEvent): string {
  const p = e.payload ?? {};
  const str = (v: unknown) => (typeof v === "string" ? v : v === undefined ? "" : JSON.stringify(v));
  switch (e.type) {
    case "agent_start": return `started${p.kind ? ` (${str(p.kind)})` : ""}`;
    case "agent_end": return `finished — ${str(p.status) || "done"}`;
    case "message": return str(p.content).slice(0, 280);
    case "tool_call": return `→ ${str(p.tool)}`;
    case "tool_result": return `${p.error ? "✗" : "←"} ${str(p.tool)}${p.result ? `: ${str(p.result).slice(0, 160)}` : ""}`;
    case "collab_route": return `route → ${str(p.to ?? p.target ?? p.peer)}`;
    case "contract_check": return `contract ${str(p.passed ?? p.status)}`;
    case "terminated": return "status" in p ? `run ${str(p.status)}` : `group finished — ${str(p.reason)}`;
    case "error": return str(p.message ?? p.error);
    default: return Object.keys(p).length ? JSON.stringify(p).slice(0, 200) : "";
  }
}

function EventRow({ event: e }: { event: RunEvent }) {
  const text = summarize(e);
  return (
    <li className={`event event-${e.type}`}>
      <div className="event-head">
        <span className="event-type">{e.type.replace("_", " ")}</span>
        {e.agent && <span className="event-agent">{e.agent}</span>}
        <span className="grow" />
        <span className="muted mono">#{e.seq}</span>
      </div>
      {text && <div className="event-body">{text}</div>}
    </li>
  );
}

function SpanCosts({ runId, run }: { runId: string; run: RunDetail }) {
  const client = useClient();
  const spans = useAsync(() => client.getRunSpans(runId), [client, runId]);

  if (spans.error instanceof ForbiddenError) return null; // run-only edition: by design
  if (spans.loading && !spans.data) return null;
  // The root is always ~100%, so rank its direct children instead: that is the
  // "which step cost what" answer. Deeper spans are inside those subtrees, and
  // listing them alongside would count the same spend twice.
  const all = spans.data ?? [];
  const rootIds = new Set(all.filter((s) => !s.parent_span_id).map((s) => s.span_id));
  const children = all.filter((s) => s.parent_span_id && rootIds.has(s.parent_span_id));
  const rows = (children.length ? children : all.filter((s) => !s.parent_span_id))
    .filter((s) => s.subtree_cost_usd > 0)
    .sort((a, b) => b.subtree_cost_usd - a.subtree_cost_usd)
    .slice(0, 12);
  if (!rows.length) return null;

  const label = (s: SpanNode) => s.agent ?? s.kind;
  return (
    <Card title="Where the cost went">
      <ul className="bars">
        {rows.map((s) => (
          <li key={s.span_id}>
            <div className="row between">
              <span>{label(s)}</span>
              <span className="muted">{fmtUsd(s.subtree_cost_usd)} · {Math.round(s.subtree_share * 100)}%</span>
            </div>
            <div className="bar"><div style={{ width: `${Math.max(2, s.subtree_share * 100)}%` }} /></div>
          </li>
        ))}
      </ul>
      {run.cost_unattributed_usd > 0 && (
        <p className="list-sub">{fmtUsd(run.cost_unattributed_usd)} of spend isn't attributed to any step.</p>
      )}
    </Card>
  );
}
