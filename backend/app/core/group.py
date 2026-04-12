"""
Collaborative group executor.

Architecture recap
------------------
* One **orchestrator** agent drives the collaboration.
* Peer **worker** agents are injected into the orchestrator's CollabContext as
  callable tools (via _PeerCallTool in agent.py).
* The GroupExecutor calls orchestrator._act() once.  Internally, the
  orchestrator's LLM loop may call workers many times as tool calls.
* Turn limits are enforced via closure counters in each peer's callable wrapper.
* The orchestrator returns a TerminationSignal when it has a final answer.
  If max_total_turns is exhausted first, the GroupExecutor forces termination.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from app.core.agent import BaseAgent
from app.core.context import CollabContext
from app.core.types import AgentOutput, RunEventData, RunEventType, TerminationSignal

logger = logging.getLogger(__name__)


@dataclass
class CollabGroup:
    orchestrator: BaseAgent
    workers: dict[str, BaseAgent]       # name → agent
    max_turns_per_agent: int = 5        # how many times orchestrator may call each worker
    max_total_turns: int = 20           # global cap across all worker invocations


class GroupExecutor:
    async def execute(
        self,
        group: CollabGroup,
        task_id: str,
        run_id: str,
        task_description: str,
        tools: list,        # tools available to ALL agents
        skills: list,       # skills available to ALL agents
        emit: Callable,
    ) -> AgentOutput:
        total_calls = 0
        per_agent_calls: dict[str, int] = {name: 0 for name in group.workers}

        def make_peer_callable(worker: BaseAgent):
            async def call_peer(task: str, context: str = "") -> AgentOutput:
                nonlocal total_calls

                if total_calls >= group.max_total_turns:
                    logger.warning(
                        "Group max_total_turns=%d reached — blocking call to %r",
                        group.max_total_turns, worker.name,
                    )
                    return AgentOutput(
                        content=f"[{worker.name} call blocked: global turn limit reached]",
                        agent_name=worker.name,
                    )

                agent_calls = per_agent_calls.get(worker.name, 0)
                if agent_calls >= group.max_turns_per_agent:
                    logger.warning(
                        "Agent %r max_turns_per_agent=%d reached",
                        worker.name, group.max_turns_per_agent,
                    )
                    return AgentOutput(
                        content=f"[{worker.name} call blocked: per-agent turn limit reached]",
                        agent_name=worker.name,
                    )

                per_agent_calls[worker.name] = agent_calls + 1
                total_calls += 1

                await emit(RunEventData(
                    run_id=run_id, seq=total_calls, type=RunEventType.COLLAB_ROUTE,
                    agent=worker.name,
                    payload={"task": task[:200], "total_calls": total_calls},
                ))

                peer_ctx = CollabContext(
                    task_id=task_id,
                    run_id=run_id,
                    task_description=task,
                    curated_context=context,
                    peers={},           # workers cannot call other workers
                    tools=tools,
                    skills=skills,
                    turns_remaining=group.max_turns_per_agent - agent_calls,
                    emit=emit,
                )
                result = await worker._act(peer_ctx)
                # Workers always return AgentOutput (not TerminationSignal)
                return result if isinstance(result, AgentOutput) else result.result

            return call_peer

        peers = {name: make_peer_callable(w) for name, w in group.workers.items()}

        orch_ctx = CollabContext(
            task_id=task_id,
            run_id=run_id,
            task_description=task_description,
            curated_context="",
            peers=peers,
            tools=tools,
            skills=skills,
            turns_remaining=group.max_total_turns,
            emit=emit,
        )

        result = await group.orchestrator._act(orch_ctx)

        if isinstance(result, TerminationSignal):
            await emit(RunEventData(
                run_id=run_id, seq=total_calls + 1, type=RunEventType.TERMINATED,
                agent=group.orchestrator.name,
                payload={"reason": result.reason, "total_calls": total_calls},
            ))
            return result.result

        # Orchestrator returned AgentOutput without TerminationSignal (shouldn't
        # normally happen, but handle gracefully)
        return result
