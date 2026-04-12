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
    payload: dict
    ts: datetime

    model_config = {"from_attributes": True}


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
