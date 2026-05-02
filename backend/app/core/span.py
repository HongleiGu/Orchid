"""
Span tracking — every spawned subagent is visible and individually cancellable.

A **span** is a named unit of work executed by an asyncio.Task. Three kinds:
  - "agent"     — the root task for a run (the only one with parent=None)
  - "dag_node"  — one DAG node's agent.run() invocation
  - "peer_call" — one orchestrator → worker invocation in a CollabGroup

The persistent record lives in `run_events` (every span emits AGENT_START on
open and AGENT_END on close, both carrying span_id + parent_span_id). The
registry below is purely runtime: it maps live span_ids to their asyncio.Tasks
so a cancel call can target one subagent without aborting the whole run.

Cancellation propagates through asyncio.gather: cancelling a parent task
cancels its children. Cancelling a leaf only stops that leaf; the parent's
loop sees the cancellation as a tool_result error and decides what to do next.
"""
from __future__ import annotations

import asyncio
import contextvars
import logging
from dataclasses import dataclass, field
from typing import Literal

from ulid import ULID

logger = logging.getLogger(__name__)

SpanKind = Literal["agent", "dag_node", "peer_call"]
SpanStatus = Literal["running", "done", "cancelled", "failed"]


# Context variable holding the currently-active span_id. Each spawn rebinds
# this so child code sees its own span as the parent context.
current_span_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "orchid_current_span", default=None,
)


@dataclass
class _SpanRecord:
    span_id: str
    run_id: str
    parent_span_id: str | None
    kind: SpanKind
    agent: str | None
    task: asyncio.Task | None = None


@dataclass
class SpanRegistry:
    """Per-process map of live spans. The DB-backed history is in run_events."""

    _records: dict[str, _SpanRecord] = field(default_factory=dict)

    def open(
        self,
        run_id: str,
        kind: SpanKind,
        agent: str | None = None,
        parent_span_id: str | None = None,
    ) -> str:
        span_id = str(ULID())
        self._records[span_id] = _SpanRecord(
            span_id=span_id,
            run_id=run_id,
            parent_span_id=parent_span_id,
            kind=kind,
            agent=agent,
        )
        return span_id

    def attach_task(self, span_id: str, task: asyncio.Task) -> None:
        rec = self._records.get(span_id)
        if rec is not None:
            rec.task = task

    def close(self, span_id: str) -> None:
        self._records.pop(span_id, None)

    async def cancel(self, span_id: str) -> bool:
        """Cancel a single span's task. Children of the span will be cancelled
        by asyncio's normal task-cancellation propagation (gather, await chains)."""
        rec = self._records.get(span_id)
        if rec is None or rec.task is None or rec.task.done():
            return False
        rec.task.cancel()
        return True

    def list_for_run(self, run_id: str) -> list[dict]:
        return [
            {
                "span_id": r.span_id,
                "parent_span_id": r.parent_span_id,
                "kind": r.kind,
                "agent": r.agent,
                "running": r.task is not None and not r.task.done(),
            }
            for r in self._records.values()
            if r.run_id == run_id
        ]


# Module-level singleton
span_registry = SpanRegistry()
