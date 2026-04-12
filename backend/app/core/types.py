from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Literal


# ── LLM message primitives ────────────────────────────────────────────────────

@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class ToolResult:
    tool_call_id: str
    content: str
    is_error: bool = False


# Internal neutral message format — maps to OpenAI wire format (used by LiteLLM)
@dataclass
class Message:
    role: Literal["user", "assistant", "tool_results"]
    content: str = ""
    # populated when role == "assistant" and the model made tool calls
    tool_calls: list[ToolCall] = field(default_factory=list)
    # populated when role == "tool_results"
    results: list[ToolResult] = field(default_factory=list)

    def to_openai(self) -> list[dict]:
        """Convert to OpenAI-compatible wire format (may produce multiple dicts for tool results)."""
        if self.role == "user":
            return [{"role": "user", "content": self.content}]
        if self.role == "assistant":
            msg: dict = {"role": "assistant", "content": self.content or None}
            if self.tool_calls:
                msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.name, "arguments": __import__("json").dumps(tc.args)},
                    }
                    for tc in self.tool_calls
                ]
            return [msg]
        # tool_results → one message per result in OpenAI format
        return [
            {"role": "tool", "tool_call_id": tr.tool_call_id, "content": tr.content}
            for tr in self.results
        ]


def messages_to_openai(msgs: list[Message]) -> list[dict]:
    out: list[dict] = []
    for m in msgs:
        out.extend(m.to_openai())
    return out


# ── Agent output ──────────────────────────────────────────────────────────────

@dataclass
class AgentOutput:
    content: str
    agent_name: str = ""
    model_used: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class TerminationSignal:
    """Returned by an orchestrator's _act() to end the collaboration."""
    result: AgentOutput
    reason: Literal["done", "max_turns", "error"] = "done"


# ── Run event stream ──────────────────────────────────────────────────────────

class RunEventType(str, Enum):
    AGENT_START = "agent_start"
    AGENT_END = "agent_end"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"
    MESSAGE = "message"
    COLLAB_ROUTE = "collab_route"   # orchestrator is routing to a peer
    TERMINATED = "terminated"
    ERROR = "error"


@dataclass
class RunEventData:
    run_id: str
    seq: int
    type: RunEventType
    agent: str | None
    payload: dict
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
