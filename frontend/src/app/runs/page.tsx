"use client";

import { useState } from "react";
import Link from "next/link";
import { Badge, Button, Card, Empty } from "@/components/ui";
import { useRuns } from "@/lib/hooks";
import { formatDate } from "@/lib/utils";

export default function RunsPage() {
  const [page, setPage] = useState(1);
  const { data, isLoading } = useRuns(page);

  return (
    <>
      <h1 className="text-2xl font-bold mb-6">Runs</h1>

      {isLoading && <p className="text-sm text-muted">Loading…</p>}
      {data && data.data.length === 0 && <Empty message="No runs yet." />}

      <div className="grid gap-2">
        {data?.data.map((run) => (
          <Link key={run.id} href={`/runs/${run.id}`}>
            <Card className="flex items-center justify-between hover:border-accent/40 transition-colors cursor-pointer">
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs text-muted">{run.id.slice(0, 12)}…</span>
                <Badge value={run.status} />
                {run.model_used && (
                  <span className="text-xs text-muted">{run.model_used}</span>
                )}
              </div>
              <div className="text-xs text-muted">
                {formatDate(run.started_at ?? run.created_at)}
              </div>
            </Card>
          </Link>
        ))}
      </div>

      {data && data.meta.total > data.meta.page_size && (
        <div className="flex gap-2 justify-center mt-4">
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage(page - 1)}>Prev</Button>
          <span className="text-sm text-muted py-1.5">Page {page}</span>
          <Button variant="secondary" size="sm" disabled={page * data.meta.page_size >= data.meta.total} onClick={() => setPage(page + 1)}>Next</Button>
        </div>
      )}
    </>
  );
}
