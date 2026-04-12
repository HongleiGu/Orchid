"use client";

import { Card } from "@/components/ui";
import { useAgents, useRuns, useTasks } from "@/lib/hooks";
import { Bot, ListChecks, Play } from "lucide-react";

export default function DashboardPage() {
  const agents = useAgents();
  const tasks = useTasks();
  const runs = useRuns();

  const stats = [
    { label: "Agents", value: agents.data?.meta.total ?? 0, icon: Bot },
    { label: "Tasks", value: tasks.data?.meta.total ?? 0, icon: ListChecks },
    { label: "Runs", value: runs.data?.meta.total ?? 0, icon: Play },
  ];

  return (
    <>
      <h1 className="text-2xl font-bold mb-6">Dashboard</h1>
      <div className="grid grid-cols-3 gap-4 mb-8">
        {stats.map(({ label, value, icon: Icon }) => (
          <Card key={label} className="flex items-center gap-4">
            <div className="p-3 rounded-lg bg-accent/10">
              <Icon size={22} className="text-accent" />
            </div>
            <div>
              <p className="text-2xl font-bold">{value}</p>
              <p className="text-sm text-muted">{label}</p>
            </div>
          </Card>
        ))}
      </div>

      <Card>
        <h2 className="font-semibold mb-3">Recent runs</h2>
        {runs.data?.data.length === 0 && (
          <p className="text-sm text-muted">No runs yet. Create a task and trigger it.</p>
        )}
        <div className="space-y-2">
          {runs.data?.data.slice(0, 5).map((run) => (
            <div key={run.id} className="flex items-center justify-between text-sm border-b border-border pb-2 last:border-0">
              <span className="font-mono text-xs text-muted">{run.id.slice(0, 12)}…</span>
              <span className={`text-xs font-medium ${
                run.status === "done" ? "text-success" :
                run.status === "failed" ? "text-danger" :
                run.status === "running" ? "text-warning" : "text-muted"
              }`}>{run.status}</span>
            </div>
          ))}
        </div>
      </Card>
    </>
  );
}
