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
from app.core.span import current_span_id, span_registry
from app.core.types import AgentOutput, RunEventData, RunEventType
from app.db.models.agent import Agent as AgentORM
from app.db.models.run import Run, RunEvent
from app.db.models.task import Task
from app.db.session import AsyncSessionLocal
from app.skills.registry import skill_registry

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
    # Attach a logger so a silent crash in the consumer loop is visible — without
    # this, asyncio.create_task swallows the exception and runs queue forever.
    _consumer_task.add_done_callback(_log_consumer_exit)
    logger.info("Run consumer started")


def _log_consumer_exit(task: asyncio.Task) -> None:
    if task.cancelled():
        logger.info("Run consumer cancelled")
        return
    exc = task.exception()
    if exc is not None:
        logger.error("Run consumer crashed — runs will pile up pending", exc_info=exc)
    else:
        logger.info("Run consumer exited cleanly")


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
        # Default span fields from the live contextvar so callers don't have
        # to wire span_id through every emit site.
        if event.span_id is None:
            event.span_id = current_span_id.get()
        async with AsyncSessionLocal() as db:
            db.add(RunEvent(
                run_id=event.run_id,
                seq=event.seq,
                type=event.type.value,
                agent=event.agent,
                span_id=event.span_id,
                parent_span_id=event.parent_span_id,
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
            "span_id": event.span_id,
            "parent_span_id": event.parent_span_id,
            "payload": event.payload,
            "ts": event.ts.isoformat(),
        })

    # Open the root span. Runs to completion inside the wrapper task; the
    # cancel_run() API can target this span_id directly for a whole-run kill.
    root_span_id = span_registry.open(run_id=run_id, kind="agent", agent=None)
    span_registry.attach_task(root_span_id, asyncio.current_task())
    current_span_id.set(root_span_id)
    await emit(RunEventData(
        run_id=run_id, seq=0, type=RunEventType.AGENT_START,
        agent=None, span_id=root_span_id, parent_span_id=None,
        payload={"kind": "run"},
    ))

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

            # Auto-save every successful run's content to the vault. Skipped
            # if the workflow opted out via `auto_save: false` in workflow_config.
            cfg = task_obj.workflow_config or {} if task_obj else {}
            if (
                task_obj
                and output.content
                and cfg.get("auto_save", True)
            ):
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
    finally:
        span_registry.close(root_span_id)


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

    raise ValueError(
        f"Unknown workflow_type: {wtype!r}. Supported: single | dag | group. "
        "(pipeline / passthrough were removed; express linear chains as a DAG "
        "and deterministic skill calls as a single-node DAG with a thin agent.)"
    )


async def _load_agent_orm(agent_id: str) -> AgentORM:
    async with AsyncSessionLocal() as db:
        agent = await db.get(AgentORM, agent_id)
        if agent is None:
            raise ValueError(f"Agent {agent_id} not found")
        return agent


def _orm_to_llm_agent(orm: AgentORM) -> LLMAgent:
    # Legacy `tools` column is preserved on the Agent ORM but means the same
    # thing as `skills` now — both are skill names resolved via skill_registry.
    legacy_tools = list(orm.tools or [])
    skills = list(orm.skills or [])
    merged: list[str] = []
    for name in legacy_tools + skills:
        if name not in merged:
            merged.append(name)
    return LLMAgent(
        name=orm.name,
        model=orm.model or settings.llm_default_model,
        system_prompt=orm.system_prompt,
        skill_names=merged,
        reasoning=getattr(orm, "reasoning", False),
    )


def _resolve_skills(agent: LLMAgent):
    return skill_registry.resolve(agent.skill_names) if agent.skill_names else []


async def _run_single(task: Task, run_id: str, emit, override_inputs: dict | None = None) -> AgentOutput:
    if not task.agent_id:
        raise ValueError("Single-agent task has no agent_id")
    orm = await _load_agent_orm(task.agent_id)
    agent = _orm_to_llm_agent(orm)
    skills = _resolve_skills(agent)

    from app.core.context import DAGContext
    ctx = DAGContext(
        task_id=task.id,
        run_id=run_id,
        task_description=task.description or task.name,
        inputs=override_inputs if override_inputs is not None else (task.inputs or {}),
        skills=skills,
        emit=emit,
    )
    return await agent.run(ctx)


async def _run_dag(task: Task, cfg: dict, run_id: str, emit) -> AgentOutput:
    """JSON config shape:
        {
          "nodes": [
            {"name": "search", "agent_id": "...", "outputs": {...}},
            {"name": "summarise", "agent_id": "...", "inputs": {...}}
          ],
          "edges": [
            {"source": "search", "target": "summarise"},
            {"source": "search", "target": "skip", "if": "'no results' in output.content.lower()"}
          ],
          "entry": "search"   # optional; defaults to first node
        }
    """
    node_cfgs: list[dict] = cfg.get("nodes", [])
    edge_cfgs: list[dict] = cfg.get("edges", [])
    entry: str = cfg.get("entry", node_cfgs[0]["name"] if node_cfgs else "")

    nodes: dict[str, DAGNode] = {}
    all_skills: list = []

    for nc in node_cfgs:
        orm = await _load_agent_orm(nc["agent_id"])
        agent = _orm_to_llm_agent(orm)
        all_skills.extend(_resolve_skills(agent))
        nodes[nc["name"]] = DAGNode(
            name=nc["name"],
            agent=agent,
            inputs=nc.get("inputs"),
            outputs=nc.get("outputs"),
        )

    edges = [
        DAGEdge(
            source=e["source"],
            target=e["target"],
            condition=e.get("if") or e.get("condition"),
        )
        for e in edge_cfgs
    ]
    dag = DAGDefinition(nodes=nodes, edges=edges, entry=entry)

    return await DAGExecutor().execute(
        dag=dag, task_id=task.id, run_id=run_id,
        task_description=task.description or task.name,
        inputs=task.inputs or {},
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
    all_skills: list = []

    for wid in worker_ids:
        orm = await _load_agent_orm(wid)
        agent = _orm_to_llm_agent(orm)
        all_skills.extend(_resolve_skills(agent))
        workers[orm.name] = agent

    all_skills.extend(_resolve_skills(orchestrator))

    group = CollabGroup(
        orchestrator=orchestrator,
        workers=workers,
        max_turns_per_agent=max_turns_per,
        max_total_turns=max_total,
    )

    return await GroupExecutor().execute(
        group=group, task_id=task.id, run_id=run_id,
        task_description=task.description or task.name,
        skills=list({s.name: s for s in all_skills}.values()),
        emit=emit,
    )


def _auto_save_to_vault(task_name: str, run_id: str, content: str) -> None:
    """Persist a successful run's output to the vault as a markdown file.
    Best-effort — failures here don't fail the run."""
    try:
        import re
        from pathlib import Path
        import os

        vault_dir = Path(os.environ.get("VAULT_DIR", "/app/vault"))
        project = re.sub(r"[^\w\-. ]", "", task_name).strip().lower().replace(" ", "-") or "runs"
        project_dir = vault_dir / project
        project_dir.mkdir(parents=True, exist_ok=True)

        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"{date_str}-{run_id[:8]}.md"
        (project_dir / filename).write_text(content, encoding="utf-8")
        logger.info("Auto-saved run output to vault: %s/%s", project, filename)
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
