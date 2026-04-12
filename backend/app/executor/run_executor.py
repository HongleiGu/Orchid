"""
RunExecutor — adapter between DB/API and the core engines, plus the strict
sequential queue consumer.

Queue model
-----------
- Runs are inserted as `status="pending"` rows by the API or scheduler.
- A single consumer (started in main.py lifespan) claims the highest-priority
  oldest pending row, executes it, then loops.
- `notify_new_run()` wakes the consumer immediately on insert; otherwise it
  polls every 2s.
- Cancellation works for both pending (DB flip) and running (asyncio.cancel)
  states.
- Crash recovery on startup marks any `status="running"` rows as failed.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.agent import LLMAgent
from app.core.dag import DAGDefinition, DAGEdge, DAGExecutor, DAGNode
from app.core.group import CollabGroup, GroupExecutor
from app.core.types import AgentOutput, RunEventData, RunEventType
from app.db.models.agent import Agent as AgentORM
from app.db.models.run import Run, RunEvent
from app.db.models.task import Task
from app.db.session import AsyncSessionLocal
from app.skills.registry import skill_registry
from app.tools.registry import tool_registry

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Consumer state ────────────────────────────────────────────────────────────
# Single consumer task; only one run executes at a time.
_wakeup: asyncio.Event = asyncio.Event()
_consumer_task: asyncio.Task | None = None
_current: tuple[str, asyncio.Task] | None = None  # (run_id, task)
_shutdown: bool = False
_POLL_INTERVAL = 2.0


def notify_new_run() -> None:
    """Called by API/scheduler after inserting a pending Run row."""
    _wakeup.set()


def get_active_run_ids() -> list[str]:
    return [_current[0]] if _current else []


async def cancel_run(run_id: str) -> bool:
    """Cancel a pending or running run.

    - Pending: flip the DB row to `cancelled`.
    - Running (current): cancel the asyncio task; the wrapper writes the final state.
    """
    if _current and _current[0] == run_id:
        task = _current[1]
        if not task.done():
            task.cancel()
            return True
        return False

    async with AsyncSessionLocal() as db:
        run = await db.get(Run, run_id)
        if run is None or run.status != "pending":
            return False
        run.status = "cancelled"
        run.finished_at = datetime.now(timezone.utc)
        await db.commit()
        return True


# ── Lifecycle ─────────────────────────────────────────────────────────────────

async def start_consumer() -> None:
    """Start the queue consumer. Call once from app startup."""
    global _consumer_task, _shutdown
    if _consumer_task is not None and not _consumer_task.done():
        return
    _shutdown = False
    await _recover_interrupted_runs()
    _consumer_task = asyncio.create_task(_consumer_loop(), name="run-consumer")
    logger.info("Run consumer started")


async def stop_consumer() -> None:
    """Stop the consumer gracefully. Cancels the in-flight run if any."""
    global _shutdown
    _shutdown = True
    _wakeup.set()
    if _current and not _current[1].done():
        _current[1].cancel()
    if _consumer_task is not None:
        try:
            await _consumer_task
        except asyncio.CancelledError:
            pass
    logger.info("Run consumer stopped")


async def _recover_interrupted_runs() -> None:
    """Mark any runs left in `running` (from a previous crash) as failed,
    and reset Task.status accordingly."""
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Run).where(Run.status == "running"))
        stuck = result.scalars().all()
        now = datetime.now(timezone.utc)
        for run in stuck:
            run.status = "failed"
            run.error = "Interrupted by server restart"
            run.finished_at = now
            task = await db.get(Task, run.task_id)
            if task and task.status == "running":
                task.status = "idle"
        if stuck:
            logger.warning("Recovered %d interrupted run(s) on startup", len(stuck))
        await db.commit()


# ── Consumer loop ─────────────────────────────────────────────────────────────

async def _consumer_loop() -> None:
    global _current
    while not _shutdown:
        run_info = await _claim_next()
        if run_info is None:
            try:
                await asyncio.wait_for(_wakeup.wait(), timeout=_POLL_INTERVAL)
            except asyncio.TimeoutError:
                pass
            _wakeup.clear()
            continue

        run_id, task_id, runtime_params = run_info
        task = asyncio.create_task(
            _run_wrapper(task_id, run_id, runtime_params), name=f"run-{run_id}"
        )
        _current = (run_id, task)
        try:
            await task
        except asyncio.CancelledError:
            # Wrapper handles its own cleanup on cancel; nothing to do here.
            pass
        except Exception:
            # Wrapper already logged + persisted the failure.
            pass
        finally:
            _current = None


async def _claim_next() -> tuple[str, str, dict] | None:
    """Atomically pick the next pending run and mark it running.

    With a single consumer there's no contention — no row-level lock needed.
    Returns (run_id, task_id, runtime_params) or None if queue is empty.
    """
    async with AsyncSessionLocal() as db:
        # ULID `id` is the tiebreaker — it's time-sortable, so batch-inserted
        # rows with identical created_at still execute in insertion order.
        result = await db.execute(
            select(Run)
            .where(Run.status == "pending")
            .order_by(Run.priority.desc(), Run.created_at.asc(), Run.id.asc())
            .limit(1)
        )
        run = result.scalar_one_or_none()
        if run is None:
            return None

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        task = await db.get(Task, run.task_id)
        if task:
            task.status = "running"
            task.last_run_at = run.started_at
        await db.commit()
        return run.id, run.task_id, dict(run.runtime_params or {})


# ── Internal ──────────────────────────────────────────────────────────────────

async def _run_wrapper(task_id: str, run_id: str, runtime_params: dict | None = None) -> None:
    """Top-level coroutine — catches all exceptions and writes final DB state."""
    async with AsyncSessionLocal() as db:
        run = await db.get(Run, run_id)
        if run is None:
            logger.error("Run %s not found in DB", run_id)
            return

        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        await db.commit()

    seq_counter = _SeqCounter()

    async def emit(event: RunEventData) -> None:
        event.seq = seq_counter.next()
        async with AsyncSessionLocal() as db:
            db.add(RunEvent(
                run_id=event.run_id,
                seq=event.seq,
                type=event.type.value,
                agent=event.agent,
                payload=event.payload,
                ts=event.ts,
            ))
            await db.commit()
        # Broadcast to WebSocket subscribers
        from app.ws.manager import ws_manager
        await ws_manager.broadcast(run_id, {
            "seq": event.seq,
            "type": event.type.value,
            "agent": event.agent,
            "payload": event.payload,
            "ts": event.ts.isoformat(),
        })

    try:
        output = await _execute(task_id, run_id, emit, runtime_params or {})
        async with AsyncSessionLocal() as db:
            run = await db.get(Run, run_id)
            task_obj = await db.get(Task, task_id)
            run.status = "done"
            run.finished_at = datetime.now(timezone.utc)
            run.result = {"content": output.content, "agent": output.agent_name,
                          "model": output.model_used, **output.metadata}
            run.model_used = output.model_used or None
            await _set_task_status(db, task_id, "done")
            await db.commit()

            # Auto-save to vault for pipeline tasks
            if task_obj and task_obj.workflow_type == "pipeline" and output.content:
                _auto_save_to_vault(task_obj.name, run_id, output.content)
        await emit(RunEventData(
            run_id=run_id, seq=0, type=RunEventType.TERMINATED,
            agent=None, payload={"status": "done"},
        ))
    except asyncio.CancelledError:
        async with AsyncSessionLocal() as db:
            run = await db.get(Run, run_id)
            run.status = "cancelled"
            run.finished_at = datetime.now(timezone.utc)
            await _set_task_status(db, task_id, "idle")
            await db.commit()
        await emit(RunEventData(
            run_id=run_id, seq=0, type=RunEventType.TERMINATED,
            agent=None, payload={"status": "cancelled"},
        ))
    except Exception as exc:
        logger.exception("Run %s failed", run_id)
        async with AsyncSessionLocal() as db:
            run = await db.get(Run, run_id)
            run.status = "failed"
            run.finished_at = datetime.now(timezone.utc)
            run.error = str(exc)
            await _set_task_status(db, task_id, "idle")
            await db.commit()
        await emit(RunEventData(
            run_id=run_id, seq=0, type=RunEventType.ERROR,
            agent=None, payload={"error": str(exc)},
        ))


async def _execute(
    task_id: str, run_id: str, emit, runtime_params: dict | None = None
) -> AgentOutput:
    async with AsyncSessionLocal() as db:
        task: Task | None = await db.get(Task, task_id)
        if task is None:
            raise ValueError(f"Task {task_id} not found")

    # Merge runtime params into task inputs (runtime wins on conflict)
    merged_inputs = {**(task.inputs or {}), **(runtime_params or {})}
    task.inputs = merged_inputs  # in-memory only, not persisted

    wtype = task.workflow_type
    cfg = task.workflow_config or {}

    if wtype == "single":
        return await _run_single(task, run_id, emit)
    if wtype == "dag":
        return await _run_dag(task, cfg, run_id, emit)
    if wtype == "group":
        return await _run_group(task, cfg, run_id, emit)
    if wtype == "pipeline":
        return await _run_pipeline(task, cfg, run_id, emit)

    raise ValueError(f"Unknown workflow_type: {wtype!r}")


async def _load_agent_orm(agent_id: str) -> AgentORM:
    async with AsyncSessionLocal() as db:
        agent = await db.get(AgentORM, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        return agent


def _orm_to_llm_agent(orm: AgentORM) -> LLMAgent:
    return LLMAgent(
        name=orm.name,
        model=orm.model or settings.llm_default_model,
        system_prompt=orm.system_prompt,
        tool_names=list(orm.tools or []),
        skill_names=list(orm.skills or []),
        reasoning=getattr(orm, "reasoning", False),
    )


def _resolve_tools_skills(agent: LLMAgent):
    tools = tool_registry.resolve(agent.tool_names) if agent.tool_names else []
    skills = skill_registry.resolve(agent.skill_names) if agent.skill_names else []
    return tools, skills


async def _run_single(task: Task, run_id: str, emit, override_inputs: dict | None = None) -> AgentOutput:
    if not task.agent_id:
        raise ValueError("Single-agent task has no agent_id")
    orm = await _load_agent_orm(task.agent_id)
    agent = _orm_to_llm_agent(orm)
    tools, skills = _resolve_tools_skills(agent)

    from app.core.context import DAGContext
    ctx = DAGContext(
        task_id=task.id,
        run_id=run_id,
        task_description=task.description or task.name,
        inputs=override_inputs if override_inputs is not None else (task.inputs or {}),
        tools=tools,
        skills=skills,
        emit=emit,
    )
    return await agent.run(ctx)


async def _run_dag(task: Task, cfg: dict, run_id: str, emit) -> AgentOutput:
    node_cfgs: list[dict] = cfg.get("nodes", [])
    edge_cfgs: list[dict] = cfg.get("edges", [])
    entry: str = cfg.get("entry", node_cfgs[0]["name"] if node_cfgs else "")

    nodes: dict[str, DAGNode] = {}
    all_tools: list = []
    all_skills: list = []

    for nc in node_cfgs:
        orm = await _load_agent_orm(nc["agent_id"])
        agent = _orm_to_llm_agent(orm)
        t, s = _resolve_tools_skills(agent)
        all_tools.extend(t)
        all_skills.extend(s)
        nodes[nc["name"]] = DAGNode(name=nc["name"], agent=agent)

    edges = [DAGEdge(source=e["source"], target=e["target"]) for e in edge_cfgs]
    dag = DAGDefinition(nodes=nodes, edges=edges, entry=entry)

    return await DAGExecutor().execute(
        dag=dag, task_id=task.id, run_id=run_id,
        inputs=task.inputs or {},
        tools=list({t.name: t for t in all_tools}.values()),
        skills=list({s.name: s for s in all_skills}.values()),
        emit=emit,
    )


async def _run_group(task: Task, cfg: dict, run_id: str, emit) -> AgentOutput:
    orch_id: str = cfg["orchestrator_id"]
    worker_ids: list[str] = cfg.get("worker_ids", [])
    max_turns_per = cfg.get("max_turns_per_agent", settings.default_max_turns_per_agent)
    max_total = cfg.get("max_total_turns", settings.default_max_total_turns)

    orch_orm = await _load_agent_orm(orch_id)
    orchestrator = _orm_to_llm_agent(orch_orm)

    workers: dict[str, LLMAgent] = {}
    all_tools: list = []
    all_skills: list = []

    for wid in worker_ids:
        orm = await _load_agent_orm(wid)
        agent = _orm_to_llm_agent(orm)
        t, s = _resolve_tools_skills(agent)
        all_tools.extend(t)
        all_skills.extend(s)
        workers[orm.name] = agent

    # Include orchestrator's own tools/skills too
    ot, os_ = _resolve_tools_skills(orchestrator)
    all_tools.extend(ot)
    all_skills.extend(os_)

    group = CollabGroup(
        orchestrator=orchestrator,
        workers=workers,
        max_turns_per_agent=max_turns_per,
        max_total_turns=max_total,
    )

    return await GroupExecutor().execute(
        group=group, task_id=task.id, run_id=run_id,
        task_description=task.description or task.name,
        tools=list({t.name: t for t in all_tools}.values()),
        skills=list({s.name: s for s in all_skills}.values()),
        emit=emit,
    )


async def _run_pipeline(task: Task, cfg: dict, run_id: str, emit) -> AgentOutput:
    """
    Pipeline workflow — chains multiple tasks sequentially.
    Output of step N is passed as input to step N+1 via `previous_output`.

    workflow_config format:
    {
      "steps": [
        {"task_name": "Fetch Papers", "params": {"topic": "AI agents"}},
        {"task_name": "Write Blog Post"}
      ]
    }

    Each step's params are merged with:
      - The pipeline's own task.inputs
      - {"previous_output": <content from prior step>}
    """
    steps: list[dict] = cfg.get("steps", [])
    if not steps:
        raise ValueError("Pipeline has no steps")

    logger.info("Pipeline starting with %d steps, inputs: %s",
                len(steps), list((task.inputs or {}).keys()))

    previous_output: str = ""
    last_result: AgentOutput | None = None

    for i, step in enumerate(steps):
        step_task_name: str = step.get("task_name", "")
        step_params: dict = step.get("params", {})

        # Resolve task by name — eagerly load all attributes before session closes
        async with AsyncSessionLocal() as db:
            result = await db.execute(
                select(Task).where(Task.name == step_task_name)
            )
            step_task = result.scalar_one_or_none()
            if step_task is None:
                raise ValueError(f"Pipeline step {i+1}: task {step_task_name!r} not found")
            # Force-load all attributes while session is open
            _ = step_task.id, step_task.name, step_task.description, step_task.workflow_type
            _ = step_task.workflow_config, step_task.agent_id, step_task.inputs

        # Build merged inputs:
        # - Step 1: pipeline inputs + step params (original task params)
        # - Step 2+: only step params + previous_output (don't re-inject original params)
        if i == 0:
            merged = {**(task.inputs or {}), **step_params}
        else:
            merged = {**step_params}
        if previous_output:
            merged["previous_output"] = previous_output

        # Emit pipeline step event
        await emit(RunEventData(
            run_id=run_id, seq=0, type=RunEventType.COLLAB_ROUTE,
            agent=None,
            payload={"step": i + 1, "total_steps": len(steps), "task_name": step_task_name},
        ))

        # Execute the step's task inline — pass merged inputs directly
        prev_len = len(previous_output) if previous_output else 0
        logger.info("Pipeline step %d/%d (%s): inputs keys=%s, previous_output=%d chars",
                     i + 1, len(steps), step_task_name, list(merged.keys()), prev_len)
        step_cfg = step_task.workflow_config or {}
        wtype = step_task.workflow_type

        if wtype == "single":
            step_result = await _run_single(step_task, run_id, emit, override_inputs=merged)
        elif wtype == "dag":
            step_task.inputs = merged
            step_result = await _run_dag(step_task, step_cfg, run_id, emit)
        elif wtype == "group":
            step_task.inputs = merged
            step_result = await _run_group(step_task, step_cfg, run_id, emit)
        else:
            raise ValueError(f"Pipeline step {i+1}: unsupported workflow_type {wtype!r}")

        previous_output = step_result.content
        last_result = step_result

        logger.info("Pipeline step %d/%d (%s) completed", i + 1, len(steps), step_task_name)

    if last_result is None:
        raise RuntimeError("Pipeline produced no output")
    return last_result


def _auto_save_to_vault(task_name: str, run_id: str, content: str) -> None:
    """Save pipeline output to vault as a markdown file."""
    try:
        import re
        from pathlib import Path
        import os

        vault_dir = Path(os.environ.get("VAULT_DIR", "/app/vault"))
        # Derive project name from task name
        project = re.sub(r"[^\w\-. ]", "", task_name).strip().lower().replace(" ", "-") or "pipelines"
        project_dir = vault_dir / project
        project_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"{date_str}-{run_id[:8]}.md"
        (project_dir / filename).write_text(content, encoding="utf-8")
        logger.info("Auto-saved pipeline output to vault: %s/%s", project, filename)
    except Exception as exc:
        logger.warning("Failed to auto-save to vault: %s", exc)


async def _set_task_status(db: AsyncSession, task_id: str, status: str) -> None:
    task = await db.get(Task, task_id)
    if task:
        task.status = status


class _SeqCounter:
    def __init__(self) -> None:
        self._n = 0

    def next(self) -> int:
        self._n += 1
        return self._n
