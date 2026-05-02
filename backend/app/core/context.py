from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from app.core.types import AgentOutput, RunEventData
    from app.skills.registry import Skill


@dataclass
class DAGContext:
    task_id: str
    run_id: str
    task_description: str = ""                          # human-readable task prompt
    inputs: dict = field(default_factory=dict)           # original task inputs
    upstream: dict[str, "AgentOutput"] = field(default_factory=dict)  # node_name → prior output
    skills: list["Skill"] = field(default_factory=list)
    emit: Callable[["RunEventData"], Awaitable[None]] = field(
        default=lambda _: __import__("asyncio").sleep(0)
    )


@dataclass
class CollabContext:
    task_id: str
    run_id: str
    task_description: str
    # What the orchestrator chose to pass to this specific agent
    curated_context: str = ""
    # name → async callable that invokes a peer agent; empty for worker agents
    peers: dict[str, Callable[..., Awaitable["AgentOutput"]]] = field(default_factory=dict)
    skills: list["Skill"] = field(default_factory=list)
    turns_remaining: int = 5
    emit: Callable[["RunEventData"], Awaitable[None]] = field(
        default=lambda _: __import__("asyncio").sleep(0)
    )
