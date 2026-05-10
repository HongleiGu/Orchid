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

Failed conditions DON'T decrement the target's in-degree, so a target
whose only paths are all conditional and all fail will simply be skipped.
A target with mixed conditional/unconditional paths can hang — keep
conditional ancestors in a single branch.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from app.core.agent import BaseAgent
from app.core.context import DAGContext
from app.core.span import current_span_id, span_registry
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


@dataclass
class DAGEdge:
    source: str
    target: str
    # Either a Callable[[AgentOutput], bool] or a string expression evaluated
    # with restricted globals. None = unconditional.
    condition: Callable[[AgentOutput], bool] | str | None = None


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
        output if multiple terminals exist)."""
        successors: dict[str, list[DAGEdge]] = {n: [] for n in dag.nodes}
        predecessors: dict[str, list[str]] = {n: [] for n in dag.nodes}
        in_degree: dict[str, int] = {n: 0 for n in dag.nodes}
        for edge in dag.edges:
            successors[edge.source].append(edge)
            predecessors.setdefault(edge.target, []).append(edge.source)
            in_degree[edge.target] = in_degree.get(edge.target, 0) + 1

        upstream: dict[str, AgentOutput] = {}
        completed: set[str] = set()

        # Initial frontier: every node with no incoming edges. Falls back to
        # the configured entry if all nodes have in-degree (cycle / mis-config).
        frontier = [n for n in dag.nodes if in_degree.get(n, 0) == 0]
        if not frontier:
            frontier = [dag.entry]

        last_output: AgentOutput | None = None

        while frontier:
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
            for name, output in zip(frontier, results):
                upstream[name] = output
                completed.add(name)
                last_output = output

            # Compute next frontier from edges that fired AND whose conditions
            # (if any) hold against the source's output.
            next_frontier: list[str] = []
            for name in frontier:
                src_output = upstream[name]
                for edge in successors[name]:
                    if edge.condition is not None and not _eval_condition(edge.condition, src_output):
                        continue
                    in_degree[edge.target] -= 1
                    if in_degree[edge.target] == 0 and edge.target not in completed:
                        next_frontier.append(edge.target)
            frontier = next_frontier

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
        # Per-node `inputs` (declared in workflow_config) override task-level
        # inputs for this node only. They show up in the agent's prompt
        # alongside task params, so a reused agent can branch on them
        # (e.g. paper_searcher with angle=recency vs angle=advances).
        node_inputs = {**inputs, **(node.inputs or {})}
        previous_output = _format_previous_output(upstream, predecessor_names)
        if previous_output and "previous_output" not in node_inputs:
            node_inputs["previous_output"] = previous_output
        ctx = DAGContext(
            task_id=task_id,
            run_id=run_id,
            task_description=task_description,
            inputs=node_inputs,
            upstream=upstream,
            skills=node.skills,
            emit=emit,
        )

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

        # Each parallel branch needs its own asyncio.Task so cancel-by-span
        # can target one branch without aborting siblings.
        async def _run_in_span() -> AgentOutput:
            token = current_span_id.set(child_span)
            try:
                return await node.agent.run(ctx)
            finally:
                current_span_id.reset(token)

        node_task = asyncio.create_task(
            _run_in_span(), name=f"dag-{node.name}-{child_span[:6]}",
        )
        span_registry.attach_task(child_span, node_task)
        try:
            output = await node_task
        except asyncio.CancelledError:
            if not node_task.done():
                node_task.cancel()
                try:
                    await node_task
                except (asyncio.CancelledError, Exception):
                    pass
            output = AgentOutput(
                content=f"[node {node.name} cancelled]",
                agent_name=node.agent.name,
            )
        finally:
            span_registry.close(child_span)
        return output


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
    __slots__ = ("content", "agent", "model", "metadata")

    def __init__(self, o: AgentOutput) -> None:
        self.content = o.content
        self.agent = o.agent_name
        self.model = o.model_used
        self.metadata = dict(o.metadata or {})
