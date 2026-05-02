"""
Import/export pipeline configurations as JSON.

Supports three formats:
  1. Agents only:    {"agents": [...]}
  2. Tasks only:     {"tasks": [...]}   (agent_id references must already exist)
  3. Combined:       {"agents": [...], "tasks": [...]}

On import, agents are created first so tasks can reference them by name.
Agent/task names are used as the linking key — not IDs — so configs are portable.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.api.schemas import DataResponse
from app.db.models.agent import Agent
from app.db.models.task import Task
from app.db.session import get_db

router = APIRouter(prefix="/config", tags=["config"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class AgentConfig(BaseModel):
    name: str
    role: str = "assistant"
    system_prompt: str = ""
    model: str | None = None
    tools: list[str] = []
    skills: list[str] = []
    memory_strategy: str = "none"
    reasoning: bool = False


class TaskConfig(BaseModel):
    name: str
    description: str = ""
    workflow_type: str = "single"
    workflow_config: dict = {}
    # For single-agent tasks, reference by agent name (resolved on import)
    agent_name: str | None = None
    inputs: dict = {}
    input_schema: list = []
    cron_expr: str | None = None
    default_priority: int = 0


class PipelineConfig(BaseModel):
    skills: list[str] = []   # npm package names to install, e.g. ["file:/app/examples/skill-weather"]
    agents: list[AgentConfig] = []
    tasks: list[TaskConfig] = []


class ImportResult(BaseModel):
    skills_installed: int = 0
    skills_skipped: int = 0
    agents_created: int
    agents_skipped: int
    tasks_created: int
    tasks_skipped: int
    errors: list[str]


# ── Export ────────────────────────────────────────────────────────────────────

@router.get("/export", response_model=DataResponse[PipelineConfig])
async def export_config(db: AsyncSession = Depends(get_db)):
    """Export all agents, tasks, and installed skills as a portable JSON config."""
    from app.db.models.package import InstalledPackage

    agents_orm = (await db.execute(select(Agent).order_by(Agent.created_at))).scalars().all()
    tasks_orm = (await db.execute(select(Task).order_by(Task.created_at))).scalars().all()
    packages = (await db.execute(select(InstalledPackage))).scalars().all()
    skill_names = [p.npm_name for p in packages if p.enabled]

    # Build agent id → name lookup for task references
    id_to_name: dict[str, str] = {a.id: a.name for a in agents_orm}

    agents = [
        AgentConfig(
            name=a.name,
            role=a.role,
            system_prompt=a.system_prompt,
            model=a.model,
            tools=list(a.tools or []),
            skills=list(a.skills or []),
            memory_strategy=a.memory_strategy,
            reasoning=a.reasoning,
        )
        for a in agents_orm
    ]

    tasks = []
    for t in tasks_orm:
        tc = TaskConfig(
            name=t.name,
            description=t.description,
            workflow_type=t.workflow_type,
            inputs=t.inputs or {},
            input_schema=list(t.input_schema or []),
            cron_expr=t.cron_expr,
            default_priority=t.default_priority or 0,
        )

        # Resolve agent IDs to names in workflow_config
        if t.workflow_type == "single" and t.agent_id:
            tc.agent_name = id_to_name.get(t.agent_id)
        elif t.workflow_type == "group":
            cfg = dict(t.workflow_config or {})
            orch_id = cfg.get("orchestrator_id", "")
            worker_ids = cfg.get("worker_ids", [])
            tc.workflow_config = {
                "orchestrator_name": id_to_name.get(orch_id, ""),
                "worker_names": [id_to_name.get(wid, "") for wid in worker_ids],
                "max_turns_per_agent": cfg.get("max_turns_per_agent", 5),
                "max_total_turns": cfg.get("max_total_turns", 20),
            }
        elif t.workflow_type == "dag":
            cfg = dict(t.workflow_config or {})
            nodes = cfg.get("nodes", [])
            exported_nodes = []
            for n in nodes:
                exported_nodes.append({
                    "name": n.get("name", ""),
                    "agent_name": id_to_name.get(n.get("agent_id", ""), ""),
                })
            tc.workflow_config = {
                "nodes": exported_nodes,
                "edges": cfg.get("edges", []),
                "entry": cfg.get("entry", ""),
            }
        tasks.append(tc)

    return DataResponse(data=PipelineConfig(skills=skill_names, agents=agents, tasks=tasks))


@router.get("/export/agents", response_model=DataResponse[list[AgentConfig]])
async def export_agents(db: AsyncSession = Depends(get_db)):
    """Export agents only."""
    result = await export_config(db=db)
    return DataResponse(data=result.data.agents)


@router.get("/export/tasks", response_model=DataResponse[list[TaskConfig]])
async def export_tasks(db: AsyncSession = Depends(get_db)):
    """Export tasks only (with agent name references)."""
    result = await export_config(db=db)
    return DataResponse(data=result.data.tasks)


# ── Import ────────────────────────────────────────────────────────────────────

@router.post("/import", response_model=DataResponse[ImportResult])
async def import_config(body: PipelineConfig, db: AsyncSession = Depends(get_db)):
    """Import agents and/or tasks from a JSON config."""
    return DataResponse(data=await _do_import(body, db))


@router.post("/import/upload", response_model=DataResponse[ImportResult])
async def import_config_upload(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Import from an uploaded JSON file."""
    import json

    try:
        content = await file.read()
        data = json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise HTTPException(400, f"Invalid JSON file: {exc}")

    body = PipelineConfig(**data)
    return DataResponse(data=await _do_import(body, db))


async def _do_import(body: PipelineConfig, db: AsyncSession) -> ImportResult:
    errors: list[str] = []
    skills_installed = 0
    skills_skipped = 0
    agents_created = 0
    agents_skipped = 0
    tasks_created = 0
    tasks_skipped = 0

    # 0. Install marketplace skills
    if body.skills:
        from app.marketplace.service import marketplace
        for pkg_name in body.skills:
            result = await marketplace.install(pkg_name, db)
            if result.success:
                skills_installed += 1
            elif "already installed" in (result.error or ""):
                skills_skipped += 1
            else:
                errors.append(f"Skill install '{pkg_name}': {result.error}")

    # name → id mapping (existing + newly created)
    name_to_id: dict[str, str] = {}

    # Load existing agents by name
    existing = (await db.execute(select(Agent))).scalars().all()
    for a in existing:
        name_to_id[a.name] = a.id

    # 1. Create agents
    for ac in body.agents:
        if ac.name in name_to_id:
            agents_skipped += 1
            continue
        agent_id = str(ULID())
        db.add(Agent(
            id=agent_id,
            name=ac.name,
            role=ac.role,
            system_prompt=ac.system_prompt,
            model=ac.model,
            tools=ac.tools,
            skills=ac.skills,
            memory_strategy=ac.memory_strategy,
            reasoning=ac.reasoning,
        ))
        name_to_id[ac.name] = agent_id
        agents_created += 1

    await db.flush()  # ensure agent IDs are available for task references

    # Load existing tasks by name
    existing_tasks = (await db.execute(select(Task))).scalars().all()
    existing_task_names = {t.name for t in existing_tasks}

    # 2. Create tasks
    for tc in body.tasks:
        if tc.name in existing_task_names:
            tasks_skipped += 1
            continue

        task_id = str(ULID())
        agent_id = None
        workflow_config: dict = {}

        if tc.workflow_type == "single" and tc.agent_name:
            agent_id = name_to_id.get(tc.agent_name)
            if not agent_id:
                errors.append(f"Task '{tc.name}': agent '{tc.agent_name}' not found")
                continue

        elif tc.workflow_type == "group":
            cfg = tc.workflow_config
            orch_name = cfg.get("orchestrator_name", "")
            worker_names = cfg.get("worker_names", [])
            orch_id = name_to_id.get(orch_name)
            if not orch_id:
                errors.append(f"Task '{tc.name}': orchestrator '{orch_name}' not found")
                continue
            worker_ids = []
            for wn in worker_names:
                wid = name_to_id.get(wn)
                if not wid:
                    errors.append(f"Task '{tc.name}': worker '{wn}' not found")
                else:
                    worker_ids.append(wid)
            workflow_config = {
                "orchestrator_id": orch_id,
                "worker_ids": worker_ids,
                "max_turns_per_agent": cfg.get("max_turns_per_agent", 5),
                "max_total_turns": cfg.get("max_total_turns", 20),
            }

        elif tc.workflow_type == "dag":
            cfg = tc.workflow_config
            nodes = []
            for n in cfg.get("nodes", []):
                aid = name_to_id.get(n.get("agent_name", ""))
                if not aid:
                    errors.append(f"Task '{tc.name}': DAG node agent '{n.get('agent_name')}' not found")
                    continue
                nodes.append({"name": n["name"], "agent_id": aid})
            workflow_config = {
                "nodes": nodes,
                "edges": cfg.get("edges", []),
                "entry": cfg.get("entry", ""),
            }

        db.add(Task(
            id=task_id,
            name=tc.name,
            description=tc.description,
            workflow_type=tc.workflow_type,
            workflow_config=workflow_config,
            agent_id=agent_id,
            inputs=tc.inputs,
            input_schema=tc.input_schema,
            cron_expr=tc.cron_expr,
            default_priority=tc.default_priority,
        ))
        tasks_created += 1

    await db.commit()

    # Schedule any cron tasks
    from app.scheduler.service import schedule_task
    for tc in body.tasks:
        if tc.cron_expr and tc.name not in existing_task_names:
            # Look up the ID we just created
            result = await db.execute(select(Task.id).where(Task.name == tc.name))
            tid = result.scalar_one_or_none()
            if tid:
                schedule_task(tid, tc.cron_expr)

    return ImportResult(
        skills_installed=skills_installed,
        skills_skipped=skills_skipped,
        agents_created=agents_created,
        agents_skipped=agents_skipped,
        tasks_created=tasks_created,
        tasks_skipped=tasks_skipped,
        errors=errors,
    )
