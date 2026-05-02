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
    if wtype == "passthrough":
        return await _run_passthrough(task, cfg, run_id, emit)

    raise ValueError(f"Unknown workflow_type: {wtype!r}")


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
    node_cfgs: list[dict] = cfg.get("nodes", [])
    edge_cfgs: list[dict] = cfg.get("edges", [])
    entry: str = cfg.get("entry", node_cfgs[0]["name"] if node_cfgs else "")

    nodes: dict[str, DAGNode] = {}
    all_skills: list = []

    for nc in node_cfgs:
        orm = await _load_agent_orm(nc["agent_id"])
        agent = _orm_to_llm_agent(orm)
        all_skills.extend(_resolve_skills(agent))
        nodes[nc["name"]] = DAGNode(name=nc["name"], agent=agent)

    edges = [DAGEdge(source=e["source"], target=e["target"]) for e in edge_cfgs]
    dag = DAGDefinition(nodes=nodes, edges=edges, entry=entry)

    return await DAGExecutor().execute(
        dag=dag, task_id=task.id, run_id=run_id,
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

        # Pipeline-level inputs propagate to EVERY step so user-configurable
        # settings (email_to, aspect_ratio, etc.) reach downstream agents
        # without requiring upstream steps to faithfully echo them through
        # their JSON output.
        merged = {**(task.inputs or {}), **step_params}
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
        elif wtype == "passthrough":
            step_result = await _run_passthrough(step_task, step_cfg, run_id, emit, override_inputs=merged)
        else:
            raise ValueError(f"Pipeline step {i+1}: unsupported workflow_type {wtype!r}")

        previous_output = step_result.content
        last_result = step_result

        logger.info("Pipeline step %d/%d (%s) completed", i + 1, len(steps), step_task_name)

    if last_result is None:
        raise RuntimeError("Pipeline produced no output")
    return last_result


async def _run_passthrough(
    task: Task, cfg: dict, run_id: str, emit, override_inputs: dict | None = None,
) -> AgentOutput:
    """Deterministic tool-call step — no LLM involved.

    workflow_config shape:
      {
        "calls": [
          {
            "tool": "@orchid/vault_write",
            "args": {"project": "{{vault_project}}", "content": "{{previous_output}}", ...},
            "if": "email_to"    # optional — only run if this ctx var is truthy
          },
          ...
        ]
      }

    Template substitution in `args`: `{{name}}` is replaced by the same-named
    key from (task.inputs ∪ override_inputs ∪ a few auto vars: today, now).
    A string that is EXACTLY `{{key}}` is replaced with the raw value (preserves
    bool/int types). Mixed interpolation always stringifies.
    """
    import re as _re

    calls: list[dict] = cfg.get("calls", [])
    if not calls:
        raise ValueError("passthrough task has no `calls`")

    ctx_vars: dict = {**(task.inputs or {}), **(override_inputs or {})}
    now = datetime.now(timezone.utc)
    ctx_vars.setdefault("today", now.strftime("%Y-%m-%d"))
    ctx_vars.setdefault("now", now.isoformat())

    results: list[dict] = []
    for i, call_spec in enumerate(calls):
        skill_name: str = call_spec.get("tool") or call_spec.get("skill", "")
        raw_args: dict = call_spec.get("args") or {}
        gate: str = call_spec.get("if", "")

        if gate:
            gate_val = ctx_vars.get(gate)
            if not gate_val:
                results.append({"tool": skill_name, "skipped": True, "reason": f"gate '{gate}' was falsy"})
                continue

        try:
            skill = skill_registry.get(skill_name)
        except KeyError:
            msg = f"passthrough: unknown skill {skill_name!r}"
            logger.warning(msg)
            results.append({"tool": skill_name, "ok": False, "error": msg})
            continue

        resolved = _resolve_template(raw_args, ctx_vars)
        if not isinstance(resolved, dict):
            results.append({"tool": skill_name, "ok": False, "error": "args did not resolve to an object"})
            continue

        preview = {k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v) for k, v in resolved.items()}
        await emit(RunEventData(
            run_id=run_id, seq=(i + 1) * 100, type=RunEventType.TOOL_CALL,
            agent=None, payload={"tool": skill_name, "args": preview},
        ))

        try:
            result_content = await skill.execute(**resolved)
            results.append({"tool": skill_name, "ok": True, "result_preview": str(result_content)[:200]})
            await emit(RunEventData(
                run_id=run_id, seq=(i + 1) * 100 + 1, type=RunEventType.TOOL_RESULT,
                agent=None, payload={"tool": skill_name, "result": str(result_content)[:500], "error": False},
            ))
        except Exception as exc:
            logger.exception("passthrough skill %r failed", skill_name)
            results.append({"tool": skill_name, "ok": False, "error": str(exc)})
            await emit(RunEventData(
                run_id=run_id, seq=(i + 1) * 100 + 1, type=RunEventType.TOOL_RESULT,
                agent=None, payload={"tool": skill_name, "result": str(exc), "error": True},
            ))

    # Summary as the step's "content" — short, so it doesn't inflate downstream pipeline context.
    parts = []
    for r in results:
        if r.get("skipped"):
            parts.append(f"{r['tool']} skipped")
        elif r.get("ok"):
            parts.append(f"{r['tool']} ok")
        else:
            parts.append(f"{r['tool']} FAILED: {r['error']}")
    summary = f"Passthrough: {len(results)} call(s) — " + "; ".join(parts)

    return AgentOutput(content=summary, agent_name="passthrough", metadata={"results": results})


def _resolve_template(value, ctx: dict):
    """Walk `value` (dict/list/str/other) replacing `{{name}}` tokens.

    - A string that is exactly `{{name}}` (optional whitespace) returns the raw
      ctx value, preserving its Python type (bool, int, dict, etc.).
    - Mixed strings (text around the tokens) always produce a string; each
      `{{name}}` becomes str(ctx[name]) or "" if missing.
    """
    import re as _re
    if isinstance(value, dict):
        return {k: _resolve_template(v, ctx) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_template(item, ctx) for item in value]
    if not isinstance(value, str):
        return value

    exact = _re.fullmatch(r"\s*\{\{\s*(\w+)\s*\}\}\s*", value)
    if exact:
        return ctx.get(exact.group(1))

    def _repl(match: _re.Match) -> str:
        key = match.group(1).strip()
        v = ctx.get(key)
        return "" if v is None else str(v)

    return _re.sub(r"\{\{\s*(\w+)\s*\}\}", _repl, value)


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
