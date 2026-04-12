"""
DAG executor.

A DAG is a set of named nodes (each backed by an LLMAgent) connected by
directed edges with optional conditions.  The executor performs a topological
walk, calling agent.run() on each node and feeding outputs downstream.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable

from app.core.agent import BaseAgent
from app.core.context import DAGContext
from app.core.types import AgentOutput, RunEventData, RunEventType

logger = logging.getLogger(__name__)


@dataclass
class DAGNode:
    name: str
    agent: BaseAgent


@dataclass
class DAGEdge:
    source: str
    target: str
    # If None the edge is unconditional; otherwise only followed when True
    condition: Callable[[AgentOutput], bool] | None = None


@dataclass
class DAGDefinition:
    nodes: dict[str, DAGNode]          # name → node
    edges: list[DAGEdge]
    entry: str                         # name of the first node to execute


class DAGExecutor:
    async def execute(
        self,
        dag: DAGDefinition,
        task_id: str,
        run_id: str,
        inputs: dict,
        tools: list,
        skills: list,
        emit: Callable,
    ) -> AgentOutput:
        """
        Walk the DAG in topological order and return the last node's output.
        If multiple terminal nodes exist the outputs are merged into one.
        """
        # Build adjacency and in-degree maps
        successors: dict[str, list[DAGEdge]] = {n: [] for n in dag.nodes}
        in_degree: dict[str, int] = {n: 0 for n in dag.nodes}

        for edge in dag.edges:
            successors[edge.source].append(edge)
            in_degree[edge.target] += 1

        # Topological queue seeded by entry node
        queue: list[str] = [dag.entry]
        upstream: dict[str, AgentOutput] = {}
        last_output: AgentOutput | None = None
        visited: set[str] = set()

        while queue:
            node_name = queue.pop(0)
            if node_name in visited:
                continue
            visited.add(node_name)

            node = dag.nodes[node_name]
            ctx = DAGContext(
                task_id=task_id,
                run_id=run_id,
                inputs=inputs,
                upstream={k: v for k, v in upstream.items()},
                tools=tools,
                skills=skills,
                emit=emit,
            )

            logger.debug("DAG executing node %r", node_name)
            output = await node.agent.run(ctx)
            upstream[node_name] = output
            last_output = output

            # Enqueue successors whose conditions are satisfied
            for edge in successors[node_name]:
                if edge.condition is None or edge.condition(output):
                    queue.append(edge.target)

        if last_output is None:
            raise RuntimeError("DAG produced no output — entry node may be missing.")
        return last_output
