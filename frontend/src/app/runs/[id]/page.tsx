"use client";

import { use } from "react";
import Link from "next/link";
import toast from "react-hot-toast";
import { useRouter } from "next/navigation";
import { ArrowLeft, RefreshCw, X } from "lucide-react";
import { Badge, Button, Card } from "@/components/ui";
import { ContentRenderer } from "@/components/ContentRenderer";
import { useQuery } from "@tanstack/react-query";
import { useCancelRun, useRun, useTriggerTask } from "@/lib/hooks";
import { api } from "@/lib/api";
import { formatDate } from "@/lib/utils";
import type { RunEvent } from "@/lib/types";

const EVENT_COLORS: Record<string, string> = {
  agent_start: "border-l-blue-400",
  agent_end: "border-l-blue-400",
  tool_call: "border-l-amber-400",
  tool_result: "border-l-amber-400",
  message: "border-l-green-400",
  collab_route: "border-l-purple-400",
  terminated: "border-l-gray-400",
  error: "border-l-red-400",
};

export default function RunDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const router = useRouter();
  const { data, isLoading } = useRun(id);
  const cancel = useCancelRun();
  const trigger = useTriggerTask();
  const runUsage = useQuery({
    queryKey: ["budget", "run", id],
    queryFn: () => api.budget.runUsage(id),
    enabled: !!id,
  });

  const run = data?.data;

  async function handleCancel() {
    try {
      await cancel.mutateAsync(id);
      toast.success("Cancelling…");
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  async function handleRerun() {
    if (!run) return;
    try {
      const res = await trigger.mutateAsync({ id: run.task_id });
      toast.success("New run started");
      router.push(`/runs/${res.data.run_id}`);
    } catch (e: unknown) {
      toast.error(e instanceof Error ? e.message : "Failed");
    }
  }

  if (isLoading) return <p className="text-sm text-muted">Loading…</p>;
  if (!run) return <p className="text-sm text-danger">Run not found.</p>;

  return (
    <>
      <div className="flex items-center gap-3 mb-6">
        <Link href="/runs">
          <Button variant="ghost" size="sm"><ArrowLeft size={16} /></Button>
        </Link>
        <h1 className="text-xl font-bold font-mono">{run.id.slice(0, 16)}…</h1>
        <Badge value={run.status} />
        {(run.status === "running" || run.status === "pending") && (
          <Button variant="danger" size="sm" onClick={handleCancel}>
            <X size={14} className="mr-1" /> Cancel
          </Button>
        )}
        {(run.status === "failed" || run.status === "cancelled") && (
          <Button variant="primary" size="sm" onClick={handleRerun} disabled={trigger.isPending}>
            <RefreshCw size={14} className="mr-1" /> Rerun
          </Button>
        )}
      </div>

      {/* Summary */}
      <Card className="mb-6">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm">
          <div>
            <span className="text-muted block text-xs">Task ID</span>
            <span className="font-mono text-xs">{run.task_id.slice(0, 12)}…</span>
          </div>
          <div>
            <span className="text-muted block text-xs">Model</span>
            {run.model_used ?? "—"}
          </div>
          <div>
            <span className="text-muted block text-xs">Started</span>
            {formatDate(run.started_at)}
          </div>
          <div>
            <span className="text-muted block text-xs">Finished</span>
            {formatDate(run.finished_at)}
          </div>
        </div>
        {runUsage.data?.data && (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-sm mt-3 pt-3 border-t border-border">
            <div>
              <span className="text-muted block text-xs">Input tokens</span>
              {runUsage.data.data.input_tokens.toLocaleString()}
            </div>
            <div>
              <span className="text-muted block text-xs">Output tokens</span>
              {runUsage.data.data.output_tokens.toLocaleString()}
            </div>
            <div>
              <span className="text-muted block text-xs">Total tokens</span>
              {runUsage.data.data.tokens.toLocaleString()}
            </div>
            <div>
              <span className="text-muted block text-xs">Cost</span>
              <span className="font-medium">${runUsage.data.data.cost.toFixed(4)}</span>
            </div>
          </div>
        )}

        {run.error && (
          <div className="mt-4 p-3 bg-red-50 border border-red-200 rounded text-sm text-danger">
            {run.error}
          </div>
        )}

        {run.result && (
          <div className="mt-4">
            <span className="text-xs font-medium text-muted block mb-1">Result</span>
            <div className="bg-background border border-border rounded p-3 overflow-auto max-h-125">
              <ContentRenderer
                content={
                  typeof run.result === "object" && "content" in run.result
                    ? String(run.result.content)
                    : typeof run.result === "object"
                      ? JSON.stringify(run.result, null, 2)
                      : String(run.result)
                }
              />
            </div>
          </div>
        )}
      </Card>

      {/* Event trace */}
      <h2 className="font-semibold mb-3">Event trace ({run.events?.length ?? 0})</h2>
      <div className="space-y-1">
        {run.events?.map((ev: RunEvent) => (
          <div
            key={ev.id}
            className={`border-l-4 pl-3 py-2 text-sm ${EVENT_COLORS[ev.type] ?? "border-l-gray-300"}`}
          >
            <div className="flex items-center gap-2 mb-0.5">
              <Badge value={ev.type} />
              {ev.agent && (
                <span className="text-xs font-medium text-accent">{ev.agent}</span>
              )}
              <span className="text-xs text-muted ml-auto">{formatDate(ev.ts)}</span>
            </div>
            <EventPayload payload={ev.payload} type={ev.type} />
          </div>
        ))}
        {(!run.events || run.events.length === 0) && (
          <p className="text-sm text-muted">No events yet.</p>
        )}
      </div>
    </>
  );
}

function EventPayload({ payload, type }: { payload: Record<string, unknown>; type: string }) {
  if (type === "message" && payload.content) {
    const content = String(payload.content);
    return (
      <div className="mt-1 text-xs">
        <ContentRenderer content={content.length > 1000 ? content.slice(0, 1000) + "…" : content} />
      </div>
    );
  }
  if (type === "tool_call") {
    return (
      <p className="text-xs font-mono mt-1">
        {String(payload.tool)}({JSON.stringify(payload.args).slice(0, 200)})
      </p>
    );
  }
  if (type === "tool_result") {
    const result = String(payload.result ?? "");
    return (
      <div className="mt-1 text-xs">
        <ContentRenderer content={result.length > 500 ? result.slice(0, 500) + "…" : result} />
      </div>
    );
  }
  if (type === "collab_route") {
    return (
      <p className="text-xs text-purple-600 mt-1">
        Routing task to agent…
      </p>
    );
  }
  if (type === "error") {
    return <p className="text-xs text-danger mt-1">{String(payload.error)}</p>;
  }
  return null;
}
