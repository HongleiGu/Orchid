"""
DAG executor with typed I/O, conditional edges, and parallel branch execution.

A DAG is a set of named nodes (each backed by an LLMAgent) connected by
directed edges. Each node may declare its own input/output schemas; conditional
edges decide whether downstream nodes run based on the upstream output.

Concurrency
-----------
Independent topo-sorted nodes execute in parallel via asyncio.gather. Each
node opens its own span (see app/core/span.py), so the run shows up in the
event tree as a fan-out. cancel-by-span targets one branch.

Conditional edges
-----------------
An edge with `condition: <expr>` is only traversed when the expression
evaluates truthy against the source node's output. The expression is a
Python expression evaluated with restricted globals — usable forms:
    output.content                 # non-empty content
    "ok" in output.content.lower() # keyword match
    output.metadata.get("score", 0) > 0.7

Every forward edge resolves when its source completes — either *live*
(condition passed / unconditional) or *dead* (condition failed) — and both
decrement the target's in-degree. A join node runs once all its in-edges have
resolved and at least one fired; if every in-edge is dead the node is pruned
and its own out-edges resolve dead in turn. So branches may safely merge into
a single downstream node, and a fully-untaken branch is skipped end to end.

Loops
-----
An edge with `max_iterations` (or `loop: true`) is a loop-closing (back)
edge: it points to an already-executed ancestor and, when its condition
holds, re-runs the nodes between its target and source. Example:
    {"source": "judge", "target": "design",
     "if": "'refine' in output.content.lower()", "max_iterations": 3}
Loop edges are excluded from the forward in-degree (so the graph still
topo-sorts) and are bounded per-edge by `max_iterations`. A global
`dag_max_total_node_executions` ceiling (config) stops runaway loops
regardless of per-edge budgets, returning a diagnostic halt output.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Callable

from app.config import get_settings
from app.core.agent import BaseAgent
from app.core.context import DAGContext
from app.core.span import current_span_id, span_registry
from app.models.client import model_client
from app.core.types import AgentOutput, RunEventData, RunEventType
from app.skills.registry import Skill

logger = logging.getLogger(__name__)


@dataclass
class DAGNode:
    name: str
    agent: BaseAgent
    skills: list[Skill] = field(default_factory=list)
    # Optional JSON-Schema-shaped contracts. Validated only loosely (key
    # presence) — full schema validation can land later.
    inputs: dict | None = None
    outputs: dict | None = None
    # Optional runtime verification contract. If absent, the node behaves
    # exactly like a plain DAG node. `harness` is accepted as a config alias
    # in run_executor, but the runtime stores the normalized contract here.
    contract: dict | None = None


@dataclass
class DAGEdge:
    source: str
    target: str
    # Either a Callable[[AgentOutput], bool] or a string expression evaluated
    # with restricted globals. None = unconditional.
    condition: Callable[[AgentOutput], bool] | str | None = None
    # Loop-closing (back) edge support. An edge with `max_iterations` set (or
    # `loop=True`) is treated as a cycle: it is excluded from the forward
    # topological in-degree and, when its condition holds and the budget is not
    # exhausted, re-runs its loop body instead of advancing the DAG. When
    # `loop=True` without an explicit count, `max_iterations` defaults to 1.
    max_iterations: int | None = None
    loop: bool = False

    @property
    def is_loop(self) -> bool:
        return self.loop or self.max_iterations is not None

    @property
    def iteration_budget(self) -> int:
        if self.max_iterations is not None:
            return max(0, int(self.max_iterations))
        return 1 if self.loop else 0


@dataclass
class DAGDefinition:
    nodes: dict[str, DAGNode]
    edges: list[DAGEdge]
    entry: str
    # Multiple entries are supported when in_degree==0 nodes exist.


class DAGExecutor:
    async def execute(
        self,
        dag: DAGDefinition,
        task_id: str,
        run_id: str,
        task_description: str,
        inputs: dict,
        emit: Callable,
    ) -> AgentOutput:
        """Walk the DAG executing each node, fanning out where the topology
        allows. Returns the last node's output (or the merged final-frontier
        output if multiple terminals exist).

        Forward edges drive the topological walk. Loop edges (see DAGEdge.is_loop)
        are excluded from the static in-degree so the graph still topo-sorts;
        when a loop edge's condition holds and its budget is unspent it re-runs
        its loop body. A global node-execution ceiling bounds runaway loops."""
        forward_edges = [e for e in dag.edges if not e.is_loop]
        loop_edges = [e for e in dag.edges if e.is_loop]

        successors: dict[str, list[DAGEdge]] = {n: [] for n in dag.nodes}
        loop_out: dict[str, list[DAGEdge]] = {n: [] for n in dag.nodes}
        predecessors: dict[str, list[str]] = {n: [] for n in dag.nodes}
        base_in_degree: dict[str, int] = {n: 0 for n in dag.nodes}
        fwd_adj: dict[str, list[str]] = {n: [] for n in dag.nodes}

        for edge in forward_edges:
            successors[edge.source].append(edge)
            fwd_adj.setdefault(edge.source, []).append(edge.target)
            base_in_degree[edge.target] = base_in_degree.get(edge.target, 0) + 1
        for edge in loop_edges:
            loop_out[edge.source].append(edge)
        # Prompt predecessors include loop-edge sources so a re-run node sees the
        # feedback (e.g. the judge's decision) that triggered the loop.
        for edge in dag.edges:
            predecessors.setdefault(edge.target, []).append(edge.source)

        in_degree = dict(base_in_degree)
        # live_in[n]: how many of n's resolved in-edges actually fired (condition
        # passed). A node whose in-edges have all resolved but none fired is dead
        # and gets pruned instead of run.
        live_in: dict[str, int] = {n: 0 for n in dag.nodes}
        upstream: dict[str, AgentOutput] = {}
        completed: set[str] = set()
        pruned: set[str] = set()
        loop_counts: dict[int, int] = {}
        total_executions = 0
        max_total = get_settings().dag_max_total_node_executions

        # Initial frontier: every node with no forward in-edges. Falls back to
        # the configured entry if all nodes have in-degree (pure cycle).
        frontier = [n for n in dag.nodes if in_degree.get(n, 0) == 0]
        if not frontier:
            frontier = [dag.entry]

        last_output: AgentOutput | None = None

        while frontier:
            if total_executions + len(frontier) > max_total:
                logger.warning(
                    "DAG run %s hit node-execution ceiling (%d + %d > %d); halting.",
                    run_id, total_executions, len(frontier), max_total,
                )
                return _ceiling_halt_output(total_executions, len(frontier), max_total)

            results = await asyncio.gather(
                *[
                    self._run_node(
                        node=dag.nodes[name],
                        task_id=task_id,
                        run_id=run_id,
                        task_description=task_description,
                        inputs=inputs,
                        upstream=dict(upstream),  # snapshot; concurrent writes ok
                        predecessor_names=predecessors.get(name, []),
                        emit=emit,
                    )
                    for name in frontier
                ],
                return_exceptions=False,
            )
            total_executions += len(frontier)
            for name, output in zip(frontier, results):
                upstream[name] = output
                completed.add(name)
                last_output = output

            next_ready: list[str] = []

            def _decide(tgt: str) -> None:
                # Called when one of tgt's forward in-edges has just resolved.
                # When every in-edge has resolved (in_degree hits 0), the node
                # runs if any edge fired, else it is pruned (branch not taken).
                if in_degree[tgt] != 0 or tgt in completed or tgt in pruned:
                    return
                if live_in[tgt] > 0:
                    next_ready.append(tgt)
                else:
                    prune_queue.append(tgt)

            # Resolve forward edges. A halted source prunes its successors (the
            # branch stops); otherwise each edge resolves live (condition passed
            # or unconditional) or dead (condition failed). Both live and dead
            # edges decrement in_degree so a downstream join can't hang.
            prune_queue: list[str] = [n for n in frontier if _contract_halts(upstream[n])]
            for name in frontier:
                src_output = upstream[name]
                if _contract_halts(src_output):
                    continue
                for edge in successors[name]:
                    tgt = edge.target
                    if tgt in completed:
                        continue
                    live = edge.condition is None or _eval_condition(edge.condition, src_output)
                    in_degree[tgt] -= 1
                    if live:
                        live_in[tgt] += 1
                    _decide(tgt)

            # Propagate pruning: a pruned node's out-edges are all dead, which may
            # in turn prune downstream joins that have no other live path.
            while prune_queue:
                dead = prune_queue.pop()
                if dead in pruned or dead in completed:
                    continue
                pruned.add(dead)
                for edge in successors[dead]:
                    tgt = edge.target
                    if tgt in completed:
                        continue
                    in_degree[tgt] -= 1
                    _decide(tgt)

            # Loop edges: when the condition holds and budget remains, reset the
            # forward-reachable subgraph from the loop target so it (and any
            # conditional exits downstream of it) re-evaluate. Processed after
            # forward resolution so the reset is authoritative for re-entry.
            for name in frontier:
                src_output = upstream[name]
                if _contract_halts(src_output):
                    continue
                for edge in loop_out[name]:
                    if edge.condition is not None and not _eval_condition(edge.condition, src_output):
                        continue
                    count = loop_counts.get(id(edge), 0)
                    if count >= edge.iteration_budget:
                        logger.info(
                            "DAG loop %s→%s exhausted after %d/%d iterations.",
                            edge.source, edge.target, count, edge.iteration_budget,
                        )
                        continue
                    loop_counts[id(edge)] = count + 1
                    reset = _reachable(edge.target, fwd_adj)
                    for rn in reset:
                        completed.discard(rn)
                        pruned.discard(rn)
                        live_in[rn] = 0
                        # Re-count in-degree from forward edges whose source is
                        # also inside the reset set; edges entering from outside
                        # the loop already fired and must not gate the re-run.
                        in_degree[rn] = sum(
                            1 for fe in forward_edges
                            if fe.target == rn and fe.source in reset
                        )
                    next_ready.append(edge.target)

            # De-duplicate while preserving order (a node may be reached by both
            # a forward edge and a loop reactivation in the same tick).
            seen: set[str] = set()
            frontier = [n for n in next_ready if not (n in seen or seen.add(n))]

        if last_output is None:
            raise RuntimeError("DAG produced no output — entry node may be missing.")
        return last_output

    async def _run_node(
        self,
        node: DAGNode,
        task_id: str,
        run_id: str,
        task_description: str,
        inputs: dict,
        upstream: dict[str, AgentOutput],
        predecessor_names: list[str],
        emit: Callable,
    ) -> AgentOutput:
        parent_span = current_span_id.get()
        child_span = span_registry.open(
            run_id=run_id, kind="dag_node",
            agent=node.agent.name, parent_span_id=parent_span,
        )
        await emit(RunEventData(
            run_id=run_id, seq=0, type=RunEventType.AGENT_START,
            agent=node.agent.name,
            span_id=child_span, parent_span_id=parent_span,
            payload={"kind": "dag_node", "node": node.name},
        ))

        try:
            output = await self._run_node_with_contract(
                node=node,
                task_id=task_id,
                run_id=run_id,
                task_description=task_description,
                inputs=inputs,
                upstream=upstream,
                predecessor_names=predecessor_names,
                emit=emit,
                span_id=child_span,
            )
        except asyncio.CancelledError:
            output = AgentOutput(
                content=f"[node {node.name} cancelled]",
                agent_name=node.agent.name,
            )
        finally:
            span_registry.close(child_span)
        return output

    async def _run_node_with_contract(
        self,
        node: DAGNode,
        task_id: str,
        run_id: str,
        task_description: str,
        inputs: dict,
        upstream: dict[str, AgentOutput],
        predecessor_names: list[str],
        emit: Callable,
        span_id: str,
    ) -> AgentOutput:
        contract = node.contract or {}
        contract = _normalize_contract(contract)
        max_retries = _contract_max_retries(contract)
        consensus_cfg = contract.get("consensus") or {}
        use_consensus = int(consensus_cfg.get("n") or 1) > 1
        attempt = 0
        feedback = ""

        while True:
            if use_consensus:
                output = await self._run_consensus(
                    node=node,
                    consensus=consensus_cfg,
                    task_id=task_id,
                    run_id=run_id,
                    task_description=task_description,
                    inputs=inputs,
                    upstream=upstream,
                    predecessor_names=predecessor_names,
                    emit=emit,
                    parent_span_id=span_id,
                    contract_feedback=feedback,
                )
                tally = (output.metadata or {}).get("consensus_tally") or {}
                if not tally.get("majority_reached", True):
                    if attempt >= max_retries:
                        output.metadata = {
                            **(output.metadata or {}),
                            "contract": {
                                "status": "fail",
                                "attempt": attempt,
                                "objective": contract.get("objective", ""),
                                "passed_checks": [],
                                "failed_checks": [{
                                    "index": 0, "type": "consensus", "status": "fail",
                                    "reason": (
                                        f"No majority on {tally.get('agree_on')} after "
                                        f"{tally.get('total_trajectories')} trajectories. "
                                        f"Vote distribution: {tally.get('tally')}."
                                    ),
                                }],
                                "evidence_level": "unknown",
                                "human_review": None,
                                "retries_exhausted": True,
                                "policy": contract.get("on_exhausted") or contract.get("on_blocked") or "stop",
                            },
                            "contract_halt": True,
                        }
                        return output
                    attempt += 1
                    feedback = (
                        f"Consensus attempt {attempt} failed: no majority on "
                        f"{tally.get('agree_on')}. Vote split: {tally.get('tally')}. "
                        f"Make your {tally.get('agree_on')} value unambiguous in your output."
                    )
                    continue
            else:
                ctx = _build_node_context(
                    node=node,
                    task_id=task_id,
                    run_id=run_id,
                    task_description=task_description,
                    inputs=inputs,
                    upstream=upstream,
                    predecessor_names=predecessor_names,
                    emit=emit,
                    contract_feedback=feedback,
                )
                output = await self._run_agent_in_span(node, ctx, span_id)

            if not contract:
                return output

            verdict = await _evaluate_contract(
                node=node,
                contract=contract,
                output=output,
                task_description=task_description,
                upstream=upstream,
                run_id=run_id,
                emit=emit,
                attempt=attempt,
                span_id=span_id,
            )
            output.metadata = {**(output.metadata or {}), "contract": verdict}
            if verdict["status"] == "pass":
                return output

            policy = _resolve_contract_policy(contract, verdict)
            retries_exhausted = policy == "retry" and attempt >= max_retries
            if retries_exhausted:
                # `on_blocked` doubles as the escalation target so a contract
                # with `on_blocked: human_review` lands on the same halt path
                # as `blocked_*` verdicts. `on_exhausted` is an explicit
                # override for workflows that want a different escalation.
                policy = (
                    contract.get("on_exhausted")
                    or contract.get("on_blocked")
                    or "stop"
                )
                verdict["retries_exhausted"] = True
            verdict["policy"] = policy
            output.metadata["contract"] = verdict
            await emit(RunEventData(
                run_id=run_id, seq=0, type=RunEventType.CONTRACT_CHECK,
                agent=node.agent.name, span_id=span_id,
                payload={
                    "node": node.name,
                    "status": verdict["status"],
                    "policy": policy,
                    "attempt": attempt,
                    "evidence_level": verdict.get("evidence_level", "unknown"),
                    **({"retries_exhausted": True} if retries_exhausted else {}),
                },
            ))

            if policy == "retry":
                attempt += 1
                feedback = _format_contract_feedback(verdict, attempt, max_retries)
                continue

            if policy in {"stop", "human_review"}:
                output.metadata["contract_halt"] = True
            return output

    async def _run_agent_in_span(
        self,
        node: DAGNode,
        ctx: DAGContext,
        span_id: str,
    ) -> AgentOutput:
        # Each parallel branch needs its own asyncio.Task so cancel-by-span
        # can target one branch without aborting siblings.
        async def _run_in_span() -> AgentOutput:
            token = current_span_id.set(span_id)
            try:
                return await node.agent.run(ctx)
            finally:
                current_span_id.reset(token)

        node_task = asyncio.create_task(
            _run_in_span(), name=f"dag-{node.name}-{span_id[:6]}",
        )
        span_registry.attach_task(span_id, node_task)
        try:
            return await node_task
        except asyncio.CancelledError:
            if not node_task.done():
                node_task.cancel()
                try:
                    await node_task
                except (asyncio.CancelledError, Exception):
                    pass
            raise


    async def _run_consensus(
        self,
        node: DAGNode,
        consensus: dict,
        task_id: str,
        run_id: str,
        task_description: str,
        inputs: dict,
        upstream: dict[str, AgentOutput],
        predecessor_names: list[str],
        emit: Callable,
        parent_span_id: str,
        contract_feedback: str = "",
    ) -> AgentOutput:
        """Run the node agent N times in parallel and return the majority-vote winner.

        Each trajectory gets its own sub-span so it can be cancelled independently
        via the existing span_registry cancel-by-span mechanism. A trajectory that
        exceeds timeout_per_trajectory_s (traj_timeout=True) or raises (traj_error=True)
        is replaced with a sentinel AgentOutput and excluded from the vote count, so
        one slow or broken trajectory cannot sink the whole node.
        """
        n = max(2, int(consensus.get("n") or 3))
        agree_on = [str(f) for f in (consensus.get("agree_on") or [])]
        min_agree = int(consensus.get("min_agree") or (n // 2 + 1))
        timeout = float(consensus.get("timeout_per_trajectory_s") or 180)

        traj_span_ids: list[str] = []
        for i in range(n):
            traj_span = span_registry.open(
                run_id=run_id, kind="consensus_trajectory",
                agent=node.agent.name, parent_span_id=parent_span_id,
            )
            traj_span_ids.append(traj_span)
            await emit(RunEventData(
                run_id=run_id, seq=0, type=RunEventType.AGENT_START,
                agent=node.agent.name,
                span_id=traj_span, parent_span_id=parent_span_id,
                payload={"kind": "consensus_trajectory", "trajectory": i, "node": node.name, "n": n},
            ))

        async def run_one(i: int, traj_span: str) -> AgentOutput:
            ctx = _build_node_context(
                node=node, task_id=task_id, run_id=run_id,
                task_description=task_description, inputs=inputs,
                upstream=upstream, predecessor_names=predecessor_names,
                emit=emit, contract_feedback=contract_feedback,
            )
            try:
                return await asyncio.wait_for(
                    self._run_agent_in_span(node, ctx, traj_span),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                return AgentOutput(
                    content=f"[trajectory {i} timed out after {timeout}s]",
                    agent_name=node.agent.name,
                    model_used=node.agent.model,
                    metadata={"traj_timeout": True, "trajectory_index": i},
                )
            except asyncio.CancelledError:
                raise  # cancel-by-span must propagate, never become a vote
            except Exception as exc:  # noqa: BLE001 - one bad trajectory must not sink the vote
                logger.warning(
                    "consensus trajectory %d for node %s raised: %s", i, node.name, exc,
                )
                return AgentOutput(
                    content=f"[trajectory {i} errored: {exc}]",
                    agent_name=node.agent.name,
                    model_used=node.agent.model,
                    metadata={"traj_error": True, "trajectory_index": i, "error": str(exc)},
                )
            finally:
                span_registry.close(traj_span)

        outputs: list[AgentOutput] = await asyncio.gather(
            *[run_one(i, traj_span_ids[i]) for i in range(n)],
            return_exceptions=False,
        )

        winner, tally = _majority_vote(list(outputs), agree_on, min_agree)
        winner.metadata = {
            **(winner.metadata or {}),
            "consensus_tally": tally,
            "consensus_n": n,
            "trajectory_snippets": [o.content[:300] for o in outputs],
        }

        # Surface the vote to the run-event stream so the UI can show the split.
        await emit(RunEventData(
            run_id=run_id, seq=0, type=RunEventType.CONTRACT_CHECK,
            agent=node.agent.name, span_id=parent_span_id,
            payload={
                "kind": "consensus",
                "node": node.name,
                "n": n,
                "agree_on": agree_on,
                "min_agree": min_agree,
                "majority_reached": bool(tally.get("majority_reached", False)),
                "winner": tally.get("winner"),
                "tally": tally.get("tally", {}),
                "valid_trajectories": tally.get("valid_trajectories"),
                "total_trajectories": tally.get("total_trajectories", n),
            },
        ))
        return winner


def _eval_condition(condition: Any, output: AgentOutput) -> bool:
    """Evaluate an edge condition against an agent's output.

    Supports a callable (legacy in-process config) and a string expression
    (the JSON path). Strings are evaluated with no builtins and only `output`
    in scope — sufficient for "is this content non-empty / contains a phrase /
    has metadata.x"-shaped checks.
    """
    if callable(condition):
        try:
            return bool(condition(output))
        except Exception as exc:
            logger.warning("DAG edge condition raised: %s", exc)
            return False

    if isinstance(condition, str):
        proxy = _OutputProxy(output)
        try:
            return bool(eval(condition, {"__builtins__": {}}, {"output": proxy}))
        except Exception as exc:
            logger.warning("DAG edge expression %r raised: %s", condition, exc)
            return False

    return False


def _build_node_context(
    node: DAGNode,
    task_id: str,
    run_id: str,
    task_description: str,
    inputs: dict,
    upstream: dict[str, AgentOutput],
    predecessor_names: list[str],
    emit: Callable,
    contract_feedback: str = "",
) -> DAGContext:
    # Per-node `inputs` (declared in workflow_config) override task-level
    # inputs for this node only. They show up in the agent's prompt alongside
    # task params, so a reused agent can branch on them.
    node_inputs = {**inputs, **(node.inputs or {})}
    previous_output = _format_previous_output(upstream, predecessor_names)
    if previous_output and "previous_output" not in node_inputs:
        node_inputs["previous_output"] = previous_output
    if contract_feedback:
        node_inputs["contract_feedback"] = contract_feedback
    return DAGContext(
        task_id=task_id,
        run_id=run_id,
        task_description=task_description,
        inputs=node_inputs,
        upstream=upstream,
        skills=node.skills,
        emit=emit,
    )


async def _evaluate_contract(
    node: DAGNode,
    contract: dict,
    output: AgentOutput,
    task_description: str,
    upstream: dict[str, AgentOutput],
    run_id: str,
    emit: Callable,
    attempt: int,
    span_id: str,
) -> dict:
    await emit(RunEventData(
        run_id=run_id, seq=0, type=RunEventType.CONTRACT_CHECK,
        agent=node.agent.name, span_id=span_id,
        payload={"node": node.name, "status": "started", "attempt": attempt},
    ))

    failed: list[dict] = []
    passed: list[dict] = []
    blocked_status = ""

    checks = _contract_checks(contract)
    for idx, check in enumerate(checks):
        result = await _run_contract_check(
            node=node,
            contract=contract,
            check=check,
            output=output,
            task_description=task_description,
            upstream=upstream,
            run_id=run_id,
            index=idx,
        )
        if result.get("status") == "pass":
            passed.append(result)
        else:
            failed.append(result)
            if str(result.get("status", "")).startswith("blocked_"):
                blocked_status = str(result["status"])

    if blocked_status:
        status = blocked_status
    elif failed:
        status = "fail"
    else:
        status = "pass"

    verdict = {
        "status": status,
        "attempt": attempt,
        "objective": contract.get("objective", ""),
        "passed_checks": passed,
        "failed_checks": failed,
        "evidence_level": _infer_evidence_level(contract, output, failed, passed),
        "human_review": contract.get("human_review") if status.startswith("blocked_") else None,
    }
    await emit(RunEventData(
        run_id=run_id, seq=0, type=RunEventType.CONTRACT_CHECK,
        agent=node.agent.name, span_id=span_id,
        payload={"node": node.name, **_compact_verdict(verdict)},
    ))
    return verdict


async def _run_contract_check(
    node: DAGNode,
    contract: dict,
    check: Any,
    output: AgentOutput,
    task_description: str,
    upstream: dict[str, AgentOutput],
    run_id: str,
    index: int,
) -> dict:
    if isinstance(check, str):
        check = {"type": "llm_judge", "rubric": check}
    if not isinstance(check, dict):
        return _check_result(index, "invalid", "fail", "Contract check must be a string or object.")

    kind = check.get("type", "llm_judge")
    if kind == "contains":
        value = str(check.get("value", ""))
        ok = value in _check_field(output, check.get("field", "content"))
        return _check_result(index, kind, "pass" if ok else "fail", f"Expected output to contain {value!r}.")
    if kind == "not_contains":
        value = str(check.get("value", ""))
        ok = value not in _check_field(output, check.get("field", "content"))
        return _check_result(index, kind, "pass" if ok else "fail", f"Expected output not to contain {value!r}.")
    if kind == "starts_with":
        value = str(check.get("value", ""))
        ok = _check_field(output, check.get("field", "content")).lstrip().startswith(value)
        return _check_result(index, kind, "pass" if ok else "fail", f"Expected output to start with {value!r}.")
    if kind == "regex":
        pattern = str(check.get("pattern", ""))
        flags = re.IGNORECASE if check.get("ignore_case", False) else 0
        ok = bool(pattern and re.search(pattern, _check_field(output, check.get("field", "content")), flags))
        return _check_result(index, kind, "pass" if ok else "fail", f"Expected output to match regex {pattern!r}.")
    if kind == "json_parse":
        required_keys = [str(k) for k in (check.get("required_keys") or [])]
        ok, reason = _json_parse_check(_check_field(output, check.get("field", "content")), required_keys)
        return _check_result(index, kind, "pass" if ok else "fail", reason)
    if kind == "required_sections":
        sections = [str(s) for s in check.get("sections", [])]
        text = _check_field(output, check.get("field", "content"))
        missing = [s for s in sections if s not in text]
        ok = not missing
        return _check_result(index, kind, "pass" if ok else "fail", f"Missing required sections: {missing}.")
    if kind == "upstream_artifact":
        artifact = str(check.get("name") or check.get("node") or "")
        upstream_output = upstream.get(artifact) if artifact else None
        if not upstream_output or not upstream_output.content:
            return _check_result(
                index, kind, "fail",
                f"Required upstream artifact {artifact!r} was not available.",
            )
        upstream_contract = (upstream_output.metadata or {}).get("contract") or {}
        upstream_status = upstream_contract.get("status")
        if upstream_status and upstream_status != "pass":
            return _check_result(
                index, kind, "fail",
                f"Upstream artifact {artifact!r} did not pass its contract "
                f"(status={upstream_status!r}).",
            )
        return _check_result(
            index, kind, "pass",
            f"Upstream artifact {artifact!r} is available.",
        )
    if kind == "produces_artifact":
        artifact = str(check.get("name") or "")
        ok = _output_has_artifact(output, artifact)
        return _check_result(index, kind, "pass" if ok else "fail", f"Expected output artifact {artifact!r}.")
    if kind == "metadata_exists":
        key = str(check.get("key", ""))
        ok = key in (output.metadata or {})
        return _check_result(index, kind, "pass" if ok else "fail", f"Expected metadata key {key!r}.")
    if kind == "evidence_level":
        allowed = {str(v) for v in check.get("allowed", [])}
        actual = str((output.metadata or {}).get("evidence_level") or contract.get("evidence_level", "unknown"))
        ok = bool(allowed and actual in allowed)
        return _check_result(index, kind, "pass" if ok else "fail", f"Evidence level {actual!r} not in {sorted(allowed)}.")
    if kind == "tool_called":
        skill_name = str(check.get("skill") or check.get("name") or "")
        made = list((output.metadata or {}).get("tool_calls_made") or [])
        # Match by exact wire name OR by short name appearing as a suffix
        # (e.g. "python_experiment" matches "orchid_python_experiment").
        ok = bool(skill_name and any(
            w == skill_name or w.endswith("_" + skill_name)
            for w in made
        ))
        return _check_result(
            index, kind, "pass" if ok else "fail",
            f"Expected skill {skill_name!r} to be called. Actual tool calls: {made or ['none']}.",
        )
    if kind == "needs_human":
        reason = str(check.get("reason") or "Human input is required before this node can proceed.")
        return _check_result(index, kind, "blocked_needs_human", reason)
    if kind == "requires_secret":
        secret = str(check.get("name") or check.get("env") or "credential")
        if secret != "credential" and os.environ.get(secret):
            return _check_result(index, kind, "pass", f"Required secret {secret!r} is available.")
        return _check_result(index, kind, "blocked_needs_secret", f"Requires human-provided secret or API key: {secret}.")
    if kind == "needs_budget":
        reason = str(check.get("reason") or "Human budget approval is required before this node can proceed.")
        return _check_result(index, kind, "blocked_needs_budget", reason)
    if kind == "needs_network":
        reason = str(check.get("reason") or "Network access is required before this node can proceed.")
        return _check_result(index, kind, "blocked_needs_network", reason)
    if kind == "needs_external_access":
        reason = str(check.get("reason") or "External access is required before this node can proceed.")
        return _check_result(index, kind, "blocked_needs_external_access", reason)
    if kind == "llm_judge":
        return await _run_llm_contract_judge(
            node=node,
            contract=contract,
            check=check,
            output=output,
            task_description=task_description,
            upstream=upstream,
            run_id=run_id,
            index=index,
        )
    return _check_result(index, kind, "fail", f"Unknown contract check type: {kind!r}.")


async def _run_llm_contract_judge(
    node: DAGNode,
    contract: dict,
    check: dict,
    output: AgentOutput,
    task_description: str,
    upstream: dict[str, AgentOutput],
    run_id: str,
    index: int,
) -> dict:
    system = (
        "You are a strict workflow contract judge. Return only JSON. "
        "Do not reward fluent prose if the node failed its contract. "
        "If real-world access, credentials, budget, or human judgment is needed, "
        "use a blocked_* status instead of pass/fail."
    )
    prompt = {
        "node": node.name,
        "objective": contract.get("objective", ""),
        "rubric": check.get("rubric", ""),
        "failure_modes": contract.get("failure_modes", []),
        "task": task_description,
        "upstream": {k: v.content[:2000] for k, v in upstream.items()},
        "output": output.content[:6000],
        "tool_calls_made": list((output.metadata or {}).get("tool_calls_made") or []),
        "allowed_status": [
            "pass", "fail", "blocked_needs_human", "blocked_needs_secret",
            "blocked_needs_budget", "blocked_needs_network", "blocked_needs_external_access",
            "blocked_needs_design_decision",
        ],
        "json_schema": {
            "status": "one allowed_status value",
            "score": "0.0 to 1.0",
            "reason": "short explanation",
            "evidence_level": "real_run | dry_run | synthetic | design_only | unknown",
            "suggested_action": "short next step",
        },
    }
    response = await model_client.complete(
        model=check.get("model") or contract.get("judge_model") or get_settings().llm_default_model,
        system=system,
        history=[],
        tools=[],
        user_message=json.dumps(prompt, indent=2),
    )
    data = _extract_json(response.content)
    status = data.get("status", "fail")
    if status not in {
        "pass", "fail", "blocked_needs_human", "blocked_needs_secret",
        "blocked_needs_budget", "blocked_needs_network", "blocked_needs_external_access",
        "blocked_needs_design_decision",
    }:
        status = "fail"
    threshold = float(check.get("threshold", contract.get("threshold", 0.7)) or 0.7)
    score = float(data.get("score", 0) or 0)
    if status == "pass" and score < threshold:
        status = "fail"
    return {
        "index": index,
        "type": "llm_judge",
        "status": status,
        "score": score,
        "reason": str(data.get("reason") or response.content[:300]),
        "evidence_level": data.get("evidence_level", "unknown"),
        "suggested_action": data.get("suggested_action", ""),
    }


def _check_result(index: int, kind: str, status: str, reason: str) -> dict:
    return {"index": index, "type": kind, "status": status, "reason": reason}


def _normalize_contract(contract: dict) -> dict:
    normalized = dict(contract or {})
    if "policy" in normalized and isinstance(normalized["policy"], dict):
        policy = normalized["policy"]
        if "on_fail" not in normalized and "on_fail" in policy:
            normalized["on_fail"] = policy["on_fail"]
        if "on_blocked" not in normalized and "on_blocked" in policy:
            normalized["on_blocked"] = policy["on_blocked"]
        if "max_retries" not in normalized and "max_retries" in policy:
            normalized["max_retries"] = policy["max_retries"]
    return normalized


def _contract_max_retries(contract: dict) -> int:
    try:
        return max(0, int(contract.get("max_retries", 0) or 0))
    except (TypeError, ValueError):
        return 0


def _contract_checks(contract: dict) -> list[Any]:
    checks: list[Any] = []
    checks.extend(_checks_from_requires(contract.get("requires")))
    checks.extend(contract.get("checks", []) or [])
    checks.extend(_checks_from_produces(contract.get("produces")))
    return checks


def _checks_from_requires(requires: Any) -> list[dict]:
    checks: list[dict] = []
    if not isinstance(requires, dict):
        return checks

    artifacts = requires.get("artifacts") or requires.get("upstream") or []
    if isinstance(artifacts, str):
        artifacts = [artifacts]
    for artifact in artifacts:
        checks.append({"type": "upstream_artifact", "name": artifact})

    secrets = requires.get("secrets") or []
    if isinstance(secrets, str):
        secrets = [secrets]
    for secret in secrets:
        checks.append({"type": "requires_secret", "name": secret})

    if requires.get("network"):
        checks.append({"type": "needs_network"})
    if requires.get("external_access"):
        checks.append({"type": "needs_external_access"})
    if requires.get("budget_usd") is not None or requires.get("budget"):
        checks.append({"type": "needs_budget"})
    if requires.get("human"):
        checks.append({"type": "needs_human"})
    return checks


def _checks_from_produces(produces: Any) -> list[dict]:
    checks: list[dict] = []
    if not isinstance(produces, dict):
        return checks

    artifacts = produces.get("artifacts") or []
    if isinstance(artifacts, str):
        artifacts = [artifacts]
    for artifact in artifacts:
        checks.append({"type": "produces_artifact", "name": artifact})

    sections = produces.get("sections") or produces.get("required_sections") or []
    if isinstance(sections, str):
        sections = [sections]
    if sections:
        checks.append({"type": "required_sections", "sections": sections})

    metadata = produces.get("metadata") or []
    if isinstance(metadata, str):
        metadata = [metadata]
    for key in metadata:
        checks.append({"type": "metadata_exists", "key": key})

    if produces.get("json"):
        checks.append({"type": "json_parse"})

    evidence_levels = produces.get("evidence_level") or produces.get("evidence_levels")
    if evidence_levels:
        if isinstance(evidence_levels, str):
            evidence_levels = [evidence_levels]
        checks.append({"type": "evidence_level", "allowed": evidence_levels})
    return checks


def _check_field(output: AgentOutput, field: Any) -> str:
    if field == "content":
        return output.content or ""
    if isinstance(field, str) and field.startswith("metadata."):
        value = (output.metadata or {}).get(field.removeprefix("metadata."), "")
        return str(value)
    return ""


def _json_parse_check(text: str, required_keys: list[str] | None = None) -> tuple[bool, str]:
    candidate = (text or "").strip()
    if not candidate:
        return False, "Expected parseable JSON, got empty output."

    def _try(blob: str) -> dict | None:
        blob = blob.strip()
        s = blob.find("{")
        e = blob.rfind("}")
        if s >= 0 and e > s:
            blob = blob[s:e + 1]
        try:
            data = json.loads(blob)
            return data if isinstance(data, dict) else None
        except json.JSONDecodeError:
            return None

    # 1. Try fenced code blocks first (most explicit, avoids inline snippets).
    for block in re.findall(r"```(?:json)?\s*\n?(.*?)\n?```", candidate, re.DOTALL):
        data = _try(block)
        if data is not None:
            if required_keys:
                missing = [k for k in required_keys if k not in data]
                if missing:
                    continue
            return True, "Output contains parseable JSON."

    # 2. Whole-content fallback: if the content IS a bare JSON blob.
    if candidate.startswith("```"):
        candidate = candidate.strip("`").strip()
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    data = _try(candidate)
    if data is not None:
        if required_keys:
            missing = [k for k in required_keys if k not in data]
            if missing:
                return False, f"JSON is valid but missing required keys: {missing}."
        return True, "Output contains parseable JSON."

    return False, "Expected parseable JSON object — none found in output."


def _extract_agree_field(content: str, field: str) -> str | None:
    """Extract a vote-able value for `field` from agent output content.

    Tries JSON first (structured experiment results), then a prose pattern
    of the form 'field: value' (for judge nodes that emit 'decision: PROCEED').
    Returns a lowercased stripped string, or None if not found.
    """
    text = (content or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            data = json.loads(text[start:end + 1])
            if isinstance(data, dict) and field in data:
                return str(data[field]).strip().lower()
        except json.JSONDecodeError:
            pass
    match = re.search(rf"\b{re.escape(field)}\s*[:\s]\s*(\S+)", text, re.IGNORECASE)
    if match:
        return match.group(1).strip().lower().rstrip(".,;")
    return None


def _is_failed_trajectory(output: AgentOutput) -> bool:
    """A trajectory that timed out or raised produced no usable vote."""
    md = output.metadata or {}
    return bool(md.get("traj_timeout") or md.get("traj_error"))


def _majority_vote(
    outputs: list[AgentOutput],
    agree_on: list[str],
    min_agree: int,
) -> tuple[AgentOutput, dict]:
    """Return (winning_output, tally_dict).

    Builds a vote tuple per trajectory from the agree_on fields, counts
    plurality, and checks whether it meets min_agree. Failed trajectories
    (timed out / errored) are excluded from the vote count.
    """
    if not outputs:
        raise ValueError("consensus received zero trajectory outputs")
    if not agree_on:
        return outputs[0], {"majority_reached": True, "note": "no agree_on fields configured"}

    vote_tuples: list[tuple[str, ...] | None] = []
    for o in outputs:
        if _is_failed_trajectory(o):
            vote_tuples.append(None)
        else:
            vote_tuples.append(
                tuple(_extract_agree_field(o.content, f) or "unknown" for f in agree_on)
            )

    valid = [(i, v) for i, v in enumerate(vote_tuples) if v is not None]
    if not valid:
        return outputs[0], {
            "majority_reached": False, "error": "all_trajectories_failed",
            "tally": {}, "agree_on": agree_on,
            "valid_trajectories": 0, "total_trajectories": len(outputs),
        }

    counts: dict[str, int] = {}
    for _, v in valid:
        key = str(v)
        counts[key] = counts.get(key, 0) + 1

    winner_key = max(counts, key=lambda k: counts[k])
    winner_output = outputs[0]
    for idx, v in valid:
        if str(v) == winner_key:
            winner_output = outputs[idx]
            break

    return winner_output, {
        "majority_reached": counts[winner_key] >= min_agree,
        "winner": winner_key,
        "winner_count": counts[winner_key],
        "min_agree": min_agree,
        "tally": counts,
        "agree_on": agree_on,
        "valid_trajectories": len(valid),
        "total_trajectories": len(outputs),
    }


def _output_has_artifact(output: AgentOutput, artifact: str) -> bool:
    if not artifact:
        return False
    metadata = output.metadata or {}
    artifacts = metadata.get("artifacts") or metadata.get("artifact_paths") or []
    if isinstance(artifacts, str):
        artifacts = [artifacts]
    return artifact in artifacts or artifact in (output.content or "")


def _resolve_contract_policy(contract: dict, verdict: dict) -> str:
    if verdict["status"].startswith("blocked_"):
        return contract.get("on_blocked") or "human_review"
    policy = contract.get("on_fail") or contract.get("policy") or "annotate"
    return policy if isinstance(policy, str) else "annotate"


def _contract_halts(output: AgentOutput) -> bool:
    return bool((output.metadata or {}).get("contract_halt"))


def _reachable(start: str, adj: dict[str, list[str]]) -> set[str]:
    """Nodes reachable from `start` following `adj` (inclusive of start)."""
    seen: set[str] = {start}
    stack = [start]
    while stack:
        node = stack.pop()
        for nxt in adj.get(node, []):
            if nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _ceiling_halt_output(total: int, pending: int, cap: int) -> AgentOutput:
    """Diagnostic output returned when a DAG blows past the global node ceiling."""
    return AgentOutput(
        content=(
            f"[DAG halted: node-execution ceiling reached "
            f"({total} run + {pending} pending > {cap}). A loop likely did not "
            f"converge. Lower a loop's max_iterations or raise "
            f"dag_max_total_node_executions.]"
        ),
        agent_name="dag",
        metadata={
            "dag_halt": "node_execution_ceiling",
            "contract_halt": True,
            "total_executions": total,
            "cap": cap,
        },
    )


def _infer_evidence_level(
    contract: dict,
    output: AgentOutput,
    failed: list[dict],
    passed: list[dict],
) -> str:
    # Prefer a failing check's evidence claim (it's more informative for the
    # retry feedback); fall back to passing checks (e.g. a judge that ran to
    # completion), then to output metadata, then to the contract default.
    for result in (*failed, *passed):
        if result.get("evidence_level"):
            return str(result["evidence_level"])
    metadata = output.metadata or {}
    if metadata.get("evidence_level"):
        return str(metadata["evidence_level"])
    return str(contract.get("evidence_level", "unknown"))


def _compact_verdict(verdict: dict) -> dict:
    return {
        "status": verdict["status"],
        "attempt": verdict["attempt"],
        "evidence_level": verdict["evidence_level"],
        "failed_checks": [
            {
                "type": c.get("type"),
                "status": c.get("status"),
                "reason": str(c.get("reason", ""))[:300],
            }
            for c in verdict.get("failed_checks", [])
        ],
    }


def _format_contract_feedback(verdict: dict, attempt: int, max_retries: int) -> str:
    reasons = [
        f"- {c.get('type')}: {c.get('reason')}"
        for c in verdict.get("failed_checks", [])
    ]
    return (
        f"The previous attempt failed this node's contract "
        f"(retry {attempt} of {max_retries}). Fix the issues before answering:\n"
        + "\n".join(reasons)
    )


def _extract_json(content: str) -> dict:
    text = (content or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start:end + 1]
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _format_previous_output(
    upstream: dict[str, AgentOutput],
    predecessor_names: list[str],
) -> str:
    """Render direct predecessor output for legacy `previous_output` prompts.

    DAG-aware prompts can read `ctx.upstream` via the "Outputs from previous DAG
    nodes" block. Older pipeline-style prompts look specifically for a
    `previous_output` input, so provide a stable compatibility value here. For a
    single predecessor, pass the raw content through. For fan-in, label each
    predecessor so the downstream node can distinguish sources.
    """
    direct = [(name, upstream[name]) for name in predecessor_names if name in upstream]
    if not direct:
        return ""
    if len(direct) == 1:
        return direct[0][1].content
    return "\n\n".join(f"[{name}]\n{output.content}" for name, output in direct)


class _OutputProxy:
    """Restricted view of AgentOutput exposed to edge expressions."""
    __slots__ = ("content", "agent", "model", "metadata", "first_line")

    def __init__(self, o: AgentOutput) -> None:
        self.content = o.content
        self.agent = o.agent_name
        self.model = o.model_used
        self.metadata = dict(o.metadata or {})
        # First non-empty line, lowercased. For decision/gate nodes the verdict
        # lives on line 1 ("decision: PROCEED"); matching the whole body instead
        # lets verbose analysis prose trigger multiple branches at once, so
        # branch conditions should prefer `output.first_line`.
        self.first_line = next(
            (ln.strip().lower() for ln in (o.content or "").splitlines() if ln.strip()),
            "",
        )
