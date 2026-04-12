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
    cron_expr: str | None
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
    cron_expr: str | None = None


class TaskUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    workflow_type: str | None = None
    workflow_config: dict | None = None
    agent_id: str | None = None
    inputs: dict | None = None
    cron_expr: str | None = None


class TriggerBody(BaseModel):
    params: dict = {}  # runtime params merged with task.inputs


class TriggerOut(BaseModel):
    run_id: str
    task_id: str


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
    if task.status == "running":
        raise HTTPException(409, "Task already running")

    from datetime import timezone
    from app.executor.run_executor import submit_run

    # Merge runtime params with task defaults
    runtime_params = (body.params if body else {}) or {}

    run_id = str(ULID())
    run = Run(id=run_id, task_id=task_id, agent_id=task.agent_id)
    db.add(run)
    task.status = "running"
    task.last_run_at = datetime.now(timezone.utc)
    await db.commit()

    await submit_run(task_id, run_id, runtime_params=runtime_params)
    return DataResponse(data=TriggerOut(run_id=run_id, task_id=task_id))
