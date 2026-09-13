import { fmtDuration, fmtTime, fmtTokens, fmtUsd } from "../format";
import { useAsync, useRoute } from "../hooks";
import { useClient } from "../session";
import { Card, Empty, ErrorNote, Loading, Stat, StatusBadge } from "../ui";

export function Overview() {
  const client = useClient();
  const [, navigate] = useRoute();

  const health = useAsync(() => client.health(), [client], { pollMs: 30_000 });
  const usage = useAsync(() => client.usageSummary(30), [client]);
  const active = useAsync(() => client.listRuns({ status: "running" }), [client], { pollMs: 10_000 });
  const recent = useAsync(() => client.listRuns({ page: 1 }), [client], { pollMs: 15_000 });

  return (
    <div className="stack">
      <Card title="Server">
        <div className="row">
          <span className={`dot ${health.data?.status === "ok" ? "dot-ok" : health.error ? "dot-bad" : ""}`} />
          <span>{client.baseUrl}</span>
        </div>
        <ErrorNote error={health.error} onRetry={health.reload} />
      </Card>

      <Card title="Last 30 days">
        {usage.loading && !usage.data ? <Loading /> : (
          <div className="stats">
            <Stat label="spend" value={fmtUsd(usage.data?.cost_usd)} />
            <Stat label="tokens" value={fmtTokens(usage.data?.total_tokens)} />
            <Stat label="LLM calls" value={usage.data?.llm_calls ?? "—"} />
            <Stat label="running now" value={active.data?.meta.total ?? "—"} />
          </div>
        )}
        <ErrorNote error={usage.error} onRetry={usage.reload} />
      </Card>

      <Card title="Recent runs" action={<button className="link" onClick={() => navigate("runs")}>All</button>}>
        {recent.loading && !recent.data ? <Loading /> : recent.data?.data.length ? (
          <ul className="list">
            {recent.data.data.slice(0, 6).map((run) => (
              <li key={run.id}>
                <button className="list-item" onClick={() => navigate(`runs/${run.id}`)}>
                  <div className="list-main">
                    <StatusBadge status={run.status} />
                    <span className="mono">{run.id.slice(-8)}</span>
                  </div>
                  <div className="list-sub">
                    {fmtTime(run.created_at)} · {fmtDuration(run.started_at, run.finished_at)} · {fmtUsd(run.cost.cost_usd)}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        ) : <Empty>No runs yet.</Empty>}
        <ErrorNote error={recent.error} onRetry={recent.reload} />
      </Card>
    </div>
  );
}
