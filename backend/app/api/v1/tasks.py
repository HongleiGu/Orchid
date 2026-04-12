from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.api.schemas import DataResponse, PageMeta, PageResponse
from app.db.models.run import Run
from app.db.models.task import Task
from app.db.session import get_db

router = APIRouter(prefix="/tasks", tags=["tasks"])

_PAGE_SIZE = 20


# ── Schemas ───────────────────────────────────────────────────────────────────

class TaskOut(BaseModel):
    id: str
    name: str
    description: str
    workflow_type: str
    workflow_config: dict
    agent_id: str | None
    inputs: dict
    input_schema: list
    cron_expr: str | None
    default_priority: int
    status: str
    last_run_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TaskCreate(BaseModel):
    name: str
    description: str = ""
    workflow_type: str = "single"
    workflow_config: dict = {}
    agent_id: str | None = None
    inputs: dict = {}
    input_schema: list = []
    cron_expr: str | None = None
    default_priority: int = 0


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    workflow_type: str | None = None
    workflow_config: dict | None = None
    agent_id: str | None = None
    inputs: dict | None = None
    input_schema: list | None = None
    cron_expr: str | None = None
    default_priority: int | None = None


class TriggerBody(BaseModel):
    params: dict = {}  # runtime params merged with task.inputs
    # Higher = runs sooner. None = inherit task.default_priority.
    priority: int | None = None
    # Bypass the "already pending/running" idempotency check.
    force: bool = False


class TriggerOut(BaseModel):
    run_id: str
    task_id: str
    status: str = "pending"
    priority: int = 0


class BatchRunItem(BaseModel):
    params: dict = {}
    priority: int | None = None  # falls back to task.default_priority


class BatchTriggerBody(BaseModel):
    runs: list[BatchRunItem]


class BatchTriggerOut(BaseModel):
    task_id: str
    run_ids: list[str]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=PageResponse[TaskOut])
async def list_tasks(
    page: int = Query(1, ge=1),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    q = select(Task)
    if status:
        q = q.where(Task.status == status)
    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    rows = (
        await db.execute(q.order_by(Task.created_at.desc()).offset((page - 1) * _PAGE_SIZE).limit(_PAGE_SIZE))
    ).scalars().all()
    return PageResponse(
        data=[TaskOut.model_validate(r) for r in rows],
        meta=PageMeta(page=page, page_size=_PAGE_SIZE, total=total),
    )


@router.get("/{task_id}", response_model=DataResponse[TaskOut])
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    return DataResponse(data=TaskOut.model_validate(task))


@router.post("", response_model=DataResponse[TaskOut], status_code=201)
async def create_task(body: TaskCreate, db: AsyncSession = Depends(get_db)):
    task = Task(id=str(ULID()), **body.model_dump())
    db.add(task)
    await db.commit()
    await db.refresh(task)

    if task.cron_expr:
        from app.scheduler.service import schedule_task
        schedule_task(task.id, task.cron_expr)

    return DataResponse(data=TaskOut.model_validate(task))


@router.patch("/{task_id}", response_model=DataResponse[TaskOut])
async def update_task(
    task_id: str, body: TaskUpdate, db: AsyncSession = Depends(get_db)
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    old_cron = task.cron_expr
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(task, field, value)
    await db.commit()
    await db.refresh(task)

    from app.scheduler.service import schedule_task, unschedule_task
    if task.cron_expr and task.cron_expr != old_cron:
        schedule_task(task.id, task.cron_expr)
    elif not task.cron_expr and old_cron:
        unschedule_task(task.id)

    return DataResponse(data=TaskOut.model_validate(task))


@router.delete("/{task_id}", status_code=204)
async def delete_task(task_id: str, db: AsyncSession = Depends(get_db)):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")
    if task.cron_expr:
        from app.scheduler.service import unschedule_task
        unschedule_task(task.id)
    await db.delete(task)
    await db.commit()


@router.post("/{task_id}/trigger", response_model=DataResponse[TriggerOut])
async def trigger_task(
    task_id: str,
    body: TriggerBody | None = None,
    db: AsyncSession = Depends(get_db),
):
    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    body = body or TriggerBody()

    if not body.force:
        existing = await db.execute(
            select(Run.id)
            .where(Run.task_id == task_id, Run.status.in_(("pending", "running")))
            .limit(1)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                409, "Task already has a pending or running run (use force=true to override)"
            )

    from app.executor.run_executor import notify_new_run

    priority = body.priority if body.priority is not None else (task.default_priority or 0)
    runtime_params = body.params or {}

    run_id = str(ULID())
    db.add(Run(
        id=run_id,
        task_id=task_id,
        agent_id=task.agent_id,
        status="pending",
        priority=priority,
        runtime_params=runtime_params,
    ))
    await db.commit()

    notify_new_run()
    return DataResponse(data=TriggerOut(
        run_id=run_id, task_id=task_id, status="pending", priority=priority,
    ))


@router.post("/{task_id}/trigger/batch", response_model=DataResponse[BatchTriggerOut])
async def trigger_task_batch(
    task_id: str,
    body: BatchTriggerBody,
    db: AsyncSession = Depends(get_db),
):
    """Enqueue many runs for the same task, executed in array order.

    Bypasses the single-pending-run idempotency check by design — the whole
    point of a batch is to queue several runs for the same task.
    """
    if not body.runs:
        raise HTTPException(400, "runs must be non-empty")

    task = await db.get(Task, task_id)
    if not task:
        raise HTTPException(404, "Task not found")

    from app.executor.run_executor import notify_new_run

    default_prio = task.default_priority or 0
    run_ids: list[str] = []
    for item in body.runs:
        prio = item.priority if item.priority is not None else default_prio
        run_id = str(ULID())
        db.add(Run(
            id=run_id,
            task_id=task_id,
            agent_id=task.agent_id,
            status="pending",
            priority=prio,
            runtime_params=item.params or {},
        ))
        run_ids.append(run_id)
    await db.commit()

    notify_new_run()
    return DataResponse(data=BatchTriggerOut(task_id=task_id, run_ids=run_ids))
