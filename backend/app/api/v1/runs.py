from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DataResponse, PageMeta, PageResponse
from app.db.models.run import Run, RunEvent
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

    model_config = {"from_attributes": True}


class RunDetail(RunOut):
    events: list[RunEventOut]


class CancelOut(BaseModel):
    run_id: str
    status: str


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
    return PageResponse(
        data=[RunOut.model_validate(r) for r in rows],
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
    detail = RunDetail(
        **RunOut.model_validate(run).model_dump(),
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


# ── WebSocket stream ──────────────────────────────────────────────────────────

@router.websocket("/{run_id}/stream")
async def stream_run(run_id: str, ws: WebSocket, db: AsyncSession = Depends(get_db)):
    from app.ws.manager import ws_manager

    run = await db.get(Run, run_id)
    if not run:
        await ws.close(code=4004, reason="Run not found")
        return

    await ws_manager.connect(run_id, ws)
    try:
        await ws_manager.listen(run_id, ws)
    except WebSocketDisconnect:
        pass
    finally:
        ws_manager.disconnect(run_id, ws)
