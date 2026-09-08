"""Template catalog endpoints (OR-34).

Read-only by design. Templates ship with the release, so there is no create or
update route — and therefore nothing for the run-only profile to have to block.

Responses never include the pipeline. `Template.pipeline` is declared with
exclude=True, so the prompts and agent graph cannot leak through this surface
even if someone later returns the model directly.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.api.schemas import DataResponse
from app.db.models.run import Run
from app.db.models.task import Task
from app.db.session import get_db
from app.templates.registry import Template, template_registry

router = APIRouter(prefix="/templates", tags=["templates"])


class RunTemplateBody(BaseModel):
    inputs: dict[str, Any] = Field(default_factory=dict)
    priority: int | None = None
    force: bool = False


class RunTemplateOut(BaseModel):
    run_id: str
    template_id: str
    task_id: str
    status: str
    inputs: dict[str, Any]


@router.get("", response_model=DataResponse[list[Template]])
async def list_templates(category: str | None = None):
    """Everything runnable, optionally filtered by category."""
    items = template_registry.all()
    if category:
        items = [t for t in items if t.category == category]
    return DataResponse(data=items)


@router.get("/{template_id}", response_model=DataResponse[Template])
async def get_template(template_id: str):
    template = template_registry.get(template_id)
    if not template:
        raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")
    return DataResponse(data=template)


def _resolve_inputs(template: Template, provided: dict[str, Any]) -> dict[str, Any]:
    """Merge caller inputs over the template's declared defaults.

    Unknown keys are rejected rather than ignored. A silently dropped typo in an
    input name is the kind of thing that produces a plausible-looking but wrong
    report, which for this product is worse than an error.
    """
    declared = {i.name: i for i in template.inputs}

    unknown = sorted(set(provided) - set(declared))
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown input(s): {', '.join(unknown)}. "
                   f"Accepted: {', '.join(sorted(declared))}",
        )

    resolved: dict[str, Any] = {
        name: spec.default for name, spec in declared.items() if spec.default is not None
    }
    resolved.update(provided)

    missing = sorted(
        name for name, spec in declared.items() if spec.required and name not in resolved
    )
    if missing:
        raise HTTPException(
            status_code=422, detail=f"Missing required input(s): {', '.join(missing)}"
        )
    return resolved


async def _materialise(template: Template, db: AsyncSession) -> Task:
    """Ensure the template's pipeline exists as agents + tasks, and return its task.

    Reuses the config import path rather than duplicating agent/task creation.
    It matches on name and updates in place, so instantiating a template twice
    converges instead of creating duplicates — and a template edited in a new
    release refreshes the stored definition on next run.
    """
    from app.api.v1.config import PipelineConfig, _do_import

    pipeline_tasks = template.pipeline.get("tasks") or []
    if not pipeline_tasks:
        raise HTTPException(500, f"Template {template.id!r} defines no task")
    task_name = pipeline_tasks[0].get("name")
    if not task_name:
        raise HTTPException(500, f"Template {template.id!r} has an unnamed task")

    result = await _do_import(PipelineConfig(**template.pipeline), db)
    if result.errors:
        raise HTTPException(500, f"Template {template.id!r} failed to load: {result.errors}")

    task = (
        await db.execute(select(Task).where(Task.name == task_name))
    ).scalar_one_or_none()
    if not task:
        raise HTTPException(500, f"Template {template.id!r} produced no task {task_name!r}")
    return task


@router.post("/{template_id}/run", response_model=DataResponse[RunTemplateOut], status_code=201)
async def run_template(
    template_id: str,
    request: Request,
    body: RunTemplateBody | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Instantiate a template and queue a run (OR-33).

    This is the only way to start a run in the locked-down profile. Triggering
    an arbitrary task stays denied, so "what may run" is exactly "what shipped
    in the catalog" — Windmill's operator rule, where an operator cannot run
    anything that is not an already-deployed flow.
    """
    template = template_registry.get(template_id)
    if not template:
        raise HTTPException(404, f"Template not found: {template_id}")

    # Layer 3 narrowing (OR-38). 403 rather than 404: the template exists and is
    # listed in the catalog, so pretending otherwise would just be confusing.
    from app.plans.service import permissions_for

    user_id = getattr(request.state, "user_id", None)
    perms = await permissions_for(db, user_id)
    if not perms.allows_template(template_id):
        raise HTTPException(
            403,
            f"Template {template_id!r} is not included in your plan"
            + (f" ({perms.plan_id})" if perms.plan_id else ""),
        )

    body = body or RunTemplateBody()
    inputs = _resolve_inputs(template, body.inputs)
    task = await _materialise(template, db)

    if not body.force:
        existing = await db.execute(
            select(Run.id)
            .where(Run.task_id == task.id, Run.status.in_(("pending", "running")))
            .limit(1)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                409,
                "This template already has a pending or running run "
                "(use force=true to start another)",
            )

    from app.executor.run_executor import notify_new_run

    run_id = str(ULID())
    priority = body.priority if body.priority is not None else (task.default_priority or 0)
    db.add(Run(
        id=run_id,
        task_id=task.id,
        agent_id=task.agent_id,
        # None when authenticated with a static key, which carries no identity.
        user_id=user_id,
        status="pending",
        priority=priority,
        runtime_params=inputs,
    ))
    await db.commit()

    notify_new_run()
    return DataResponse(data=RunTemplateOut(
        run_id=run_id, template_id=template.id, task_id=task.id,
        status="pending", inputs=inputs,
    ))
