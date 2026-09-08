from __future__ import annotations

import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DataResponse, PageMeta, PageResponse
from app.db.models.run import Run, RunEvent
from app.db.models.usage import TokenUsage
from app.config import get_settings
from app.db.session import get_db

router = APIRouter(prefix="/runs", tags=["runs"])

_PAGE_SIZE = 20


# ── Schemas ───────────────────────────────────────────────────────────────────

class RunEventOut(BaseModel):
    id: int
    run_id: str
    seq: int
    type: str
    agent: str | None
    span_id: str | None = None
    parent_span_id: str | None = None
    payload: dict
    ts: datetime

    model_config = {"from_attributes": True}


class SpanNode(BaseModel):
    span_id: str
    parent_span_id: str | None
    kind: str           # "agent" | "dag_node" | "peer_call"
    agent: str | None
    started_at: datetime | None
    finished_at: datetime | None
    status: str         # "running" | "done" | "cancelled" | "failed"


class CancelSpanOut(BaseModel):
    span_id: str
    cancelled: bool


class RunCost(BaseModel):
    """What a run has cost so far, summed from token_usage."""

    cost_usd: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    llm_calls: int = 0


class AgentCost(RunCost):
    """Per-agent, per-model breakdown within one run."""

    agent: str
    model: str


class RunOut(BaseModel):
    id: str
    task_id: str
    agent_id: str | None
    status: str
    model_used: str | None
    started_at: datetime | None
    finished_at: datetime | None
    result: dict | None
    error: str | None
    created_at: datetime
    # Aggregated rather than stored on the row: token_usage is the source of
    # truth and keeps arriving while a run is in flight, so a denormalised copy
    # would be stale exactly when someone is watching it.
    cost: RunCost = RunCost()

    model_config = {"from_attributes": True}


class RunDetail(RunOut):
    events: list[RunEventOut]
    # Agent names are workflow internals, so this stays empty under the
    # run-only profile (OR-35). The total above is always available.
    cost_by_agent: list[AgentCost] = []


class CancelOut(BaseModel):
    run_id: str
    status: str


# ── Cost aggregation ──────────────────────────────────────────────────────────

async def _costs_for_runs(run_ids: list[str], db: AsyncSession) -> dict[str, RunCost]:
    """Total cost per run, for a page of runs, in one query.

    Batched by run id rather than joined onto the run query so pagination and
    ordering stay untouched and there is no risk of row multiplication.
    """
    if not run_ids:
        return {}

    rows = await db.execute(
        select(
            TokenUsage.run_id,
            func.coalesce(func.sum(TokenUsage.cost_usd), 0.0),
            func.coalesce(func.sum(TokenUsage.input_tokens), 0),
            func.coalesce(func.sum(TokenUsage.output_tokens), 0),
            func.count(),
        )
        .where(TokenUsage.run_id.in_(run_ids))
        .group_by(TokenUsage.run_id)
    )
    return {
        run_id: RunCost(
            cost_usd=float(cost), input_tokens=int(inp),
            output_tokens=int(outp), llm_calls=int(calls),
        )
        for run_id, cost, inp, outp, calls in rows.all()
    }


async def _cost_by_agent(run_id: str, db: AsyncSession) -> list[AgentCost]:
    """Per-agent, per-model breakdown for one run.

    The finest split the data supports. Attributing cost to an individual tool
    call would be an allocation rather than a measurement — a tool call spends
    no tokens itself; it costs by enlarging the context of the turns around it.
    """
    rows = await db.execute(
        select(
            TokenUsage.agent_name,
            TokenUsage.model,
            func.coalesce(func.sum(TokenUsage.cost_usd), 0.0),
            func.coalesce(func.sum(TokenUsage.input_tokens), 0),
            func.coalesce(func.sum(TokenUsage.output_tokens), 0),
            func.count(),
        )
        .where(TokenUsage.run_id == run_id)
        .group_by(TokenUsage.agent_name, TokenUsage.model)
        .order_by(func.sum(TokenUsage.cost_usd).desc())
    )
    return [
        AgentCost(
            agent=agent or "", model=model or "", cost_usd=float(cost),
            input_tokens=int(inp), output_tokens=int(outp), llm_calls=int(calls),
        )
        for agent, model, cost, inp, outp, calls in rows.all()
    ]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=PageResponse[RunOut])
async def list_runs(
    page: int = Query(1, ge=1),
    task_id: str | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Run)
    if task_id:
        q = q.where(Run.task_id == task_id)
    if status:
        q = q.where(Run.status == status)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(q.order_by(Run.created_at.desc()).offset((page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE))
    ).scalars().all()
    costs = await _costs_for_runs([r.id for r in rows], db)
    return PageResponse(
        data=[
            RunOut.model_validate(r).model_copy(update={"cost": costs.get(r.id, RunCost())})
            for r in rows
        ],
        meta=PageMeta(page=page, page_size=_PAGE_SIZE, total=total),
    )


@router.get("/{run_id}", response_model=DataResponse[RunDetail])
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    events = (
        await db.execute(
            select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.seq)
        )
    ).scalars().all()
    costs = await _costs_for_runs([run_id], db)
    # Agent names are workflow internals; the run-only edition gets the total
    # without the breakdown (OR-35).
    by_agent = (
        [] if get_settings().product_profile == "app"
        else await _cost_by_agent(run_id, db)
    )

    detail = RunDetail(
        **RunOut.model_validate(run).model_dump(exclude={"cost"}),
        cost=costs.get(run_id, RunCost()),
        cost_by_agent=by_agent,
        events=[RunEventOut.model_validate(e) for e in events],
    )
    return DataResponse(data=detail)


@router.get("/{run_id}/spans", response_model=DataResponse[list[SpanNode]])
async def list_spans(run_id: str, db: AsyncSession = Depends(get_db)):
    """Reconstruct the span tree from the immutable run_events log.

    Each AGENT_START opens a span; matching AGENT_END closes it. A span is
    "running" if no end event has been seen, otherwise it's whatever status
    the end event reported.
    """
    from app.core.span import span_registry

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    rows = (
        await db.execute(
            select(RunEvent)
            .where(RunEvent.run_id == run_id)
            .where(RunEvent.span_id.is_not(None))
            .order_by(RunEvent.seq)
        )
    ).scalars().all()

    spans: dict[str, SpanNode] = {}
    for ev in rows:
        sid = ev.span_id
        if sid not in spans:
            spans[sid] = SpanNode(
                span_id=sid,
                parent_span_id=ev.parent_span_id,
                kind=(ev.payload or {}).get("kind", "agent")
                    if ev.type == "agent_start" else "agent",
                agent=ev.agent,
                started_at=ev.ts if ev.type == "agent_start" else None,
                finished_at=None,
                status="running",
            )
        node = spans[sid]
        if ev.type == "agent_start":
            node.started_at = ev.ts
            node.kind = (ev.payload or {}).get("kind", node.kind)
        elif ev.type == "agent_end":
            node.finished_at = ev.ts
            node.status = (ev.payload or {}).get("status", "done")

    # Spans that are still running in this process get their live status
    # from the registry so the UI can see them before AGENT_END is emitted.
    live_ids = {s["span_id"] for s in span_registry.list_for_run(run_id)}
    for sid, node in spans.items():
        if node.finished_at is None and sid not in live_ids:
            # Span never closed and no live task either — likely a crashed run.
            node.status = "failed"

    return DataResponse(data=list(spans.values()))


@router.post("/{run_id}/spans/{span_id}/cancel", response_model=DataResponse[CancelSpanOut])
async def cancel_span(run_id: str, span_id: str, db: AsyncSession = Depends(get_db)):
    """Cancel one subagent's task without aborting the whole run."""
    from app.core.span import span_registry

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")

    cancelled = await span_registry.cancel(span_id)
    return DataResponse(data=CancelSpanOut(span_id=span_id, cancelled=cancelled))


@router.post("/{run_id}/cancel", response_model=DataResponse[CancelOut])
async def cancel_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    if run.status not in ("pending", "running"):
        raise HTTPException(409, f"Run is already {run.status}")

    from app.executor.run_executor import cancel_run as _cancel
    was_pending = run.status == "pending"
    cancelled = await _cancel(run_id)
    if not cancelled:
        # Race: status changed between the read and the cancel call.
        await db.refresh(run)
        return DataResponse(data=CancelOut(run_id=run_id, status=run.status))
    # Pending → cancelled is synchronous (DB flip); running → cancelling is async.
    status = "cancelled" if was_pending else "cancelling"
    return DataResponse(data=CancelOut(run_id=run_id, status=status))


# ── Event stream (SSE) ────────────────────────────────────────────────────────

# Comment frame sent when idle. Keeps proxies from closing the connection and
# lets the server notice a client that has gone away.
SSE_KEEPALIVE_SECONDS = 25


def _sse(event_id: int | None, data: str) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}data: {data}\n\n"


@router.get("/{run_id}/stream")
async def stream_run(
    run_id: str,
    request: Request,
    last_event_id: int | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Server-sent events for one run.

    SSE rather than a WebSocket because the traffic is strictly server to
    client: the socket never received anything, so the bidirectional half was
    unused. In exchange this authenticates with ordinary headers (covered by
    the same middleware as every other route, instead of a token in the query
    string that would land in access logs), and reconnects on its own.

    Resumable: a client reconnecting sends Last-Event-ID, and everything it
    missed is replayed from the durable run_events table before live streaming
    resumes. The WebSocket had no equivalent — a dropped connection simply
    stopped updating.
    """
    from app.ws.manager import ws_manager

    run = await db.get(Run, run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")

    # The browser sends the header; the query parameter is for curl and tests.
    header_id = request.headers.get("last-event-id")
    if header_id and header_id.isdigit():
        last_event_id = int(header_id)
    after_seq = last_event_id or 0

    async def event_stream():
        # Subscribe before replaying, or an event emitted between the two would
        # be lost. Anything the replay already covered is filtered out below.
        async with ws_manager.subscribe(run_id) as live:
            replayed_through = after_seq
            rows = await db.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run_id, RunEvent.seq > after_seq)
                .order_by(RunEvent.seq)
            )
            for ev in rows.scalars():
                replayed_through = ev.seq
                yield _sse(ev.seq, json.dumps({
                    "type": ev.type,
                    "agent": ev.agent,
                    "span_id": ev.span_id,
                    "parent_span_id": ev.parent_span_id,
                    "payload": ev.payload,
                    "seq": ev.seq,
                }))

            while True:
                try:
                    message = await asyncio.wait_for(
                        live.get(), timeout=SSE_KEEPALIVE_SECONDS
                    )
                except asyncio.TimeoutError:
                    # A comment frame: keeps proxies from closing an idle
                    # connection, and surfaces a client that has gone away.
                    yield ": keepalive\n\n"
                    continue

                seq = None
                try:
                    seq = json.loads(message).get("seq")
                except (ValueError, AttributeError):
                    pass
                # Skip whatever the replay already delivered.
                if isinstance(seq, int) and seq <= replayed_through:
                    continue
                yield _sse(seq, message)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            # nginx buffers proxied responses by default, which would hold events
            # until the buffer filled and defeat streaming entirely.
            "X-Accel-Buffering": "no",
        },
    )
