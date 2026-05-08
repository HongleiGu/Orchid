"""
BaseAgent ABC and concrete LLMAgent implementation.

Design recap
------------
* run(DAGContext)   — called by DAGExecutor; no peer visibility; pure input→output.
* _act(CollabContext) — called by GroupExecutor; peers are callable tools injected
                        via ctx.peers (orchestrator only); workers receive empty peers.

The internal tool-use loop (_llm_loop) is identical for both modes — the only
difference is what arrives in the context.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from abc import ABC, abstractmethod

from app.core.context import CollabContext, DAGContext
from app.core.types import (
    AgentOutput,
    Message,
    RunEventData,
    RunEventType,
    TerminationSignal,
    ToolCall,
    ToolResult,
)
from app.models.client import model_client
from app.skills.registry import Skill

logger = logging.getLogger(__name__)

# Max LLM steps (tool-use iterations) per single run/act invocation
_DEFAULT_MAX_STEPS = 20
# After this many consecutive errors, a tool is disabled for the rest of the loop
_MAX_TOOL_ERRORS = 2
# Keep the last N tool_results messages in full. Older ones are replaced with a
# compact summary before being sent back to the LLM. This cuts the quadratic
# cost of re-sending every prior tool output on every step — the dominant
# prompt_tokens cost for research-heavy agents.
_KEEP_FULL_TOOL_RESULTS = 3
# Short preview kept when summarizing a trimmed tool_result, so the LLM can
# still tell "which" tool result it was, just not re-read the full body.
_SUMMARY_PREVIEW_CHARS = 150


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        model: str,
        system_prompt: str,
        skill_names: list[str] | None = None,
        reasoning: bool = False,
    ) -> None:
        self.name = name
        self.model = model
        self.system_prompt = system_prompt
        self.skill_names: list[str] = skill_names or []
        self.reasoning = reasoning

    @abstractmethod
    async def run(self, ctx: DAGContext) -> AgentOutput: ...

    @abstractmethod
    async def _act(self, ctx: CollabContext) -> AgentOutput | TerminationSignal: ...


class LLMAgent(BaseAgent):
    """
    General-purpose LLM-backed agent.

    Both run() and _act() delegate to _llm_loop() which drives the standard
    tool-use cycle:  prompt → LLM → [tool calls → results]* → final answer.
    """

    async def run(self, ctx: DAGContext) -> AgentOutput:
        # AGENT_START is emitted by the spawn site (run_wrapper / DAGExecutor)
        # so it can stamp the right span kind. We just emit AGENT_END here.
        user_msg = _build_dag_prompt(ctx)
        output = await self._llm_loop(
            user_msg, list(ctx.skills), ctx.run_id, ctx.emit,
            task_id=ctx.task_id,
        )
        await ctx.emit(
            RunEventData(run_id=ctx.run_id, seq=0, type=RunEventType.AGENT_END,
                         agent=self.name,
                         payload={"content": output.content[:200], "status": "done"})
        )
        return output

    async def _act(self, ctx: CollabContext) -> AgentOutput | TerminationSignal:
        user_msg = ctx.task_description
        if ctx.curated_context:
            user_msg = f"{ctx.task_description}\n\n---\nContext from orchestrator:\n{ctx.curated_context}"

        # Peer agents surface as skills so the LLM can call them naturally.
        peer_skills = [_PeerCallTool(n, fn) for n, fn in ctx.peers.items()]
        all_callables = list(ctx.skills) + peer_skills

        output = await self._llm_loop(
            user_msg, all_callables, ctx.run_id, ctx.emit,
            max_steps=ctx.turns_remaining * 2,
            task_id=ctx.task_id,
        )
        await ctx.emit(
            RunEventData(run_id=ctx.run_id, seq=0, type=RunEventType.AGENT_END,
                         agent=self.name,
                         payload={"content": output.content[:200], "status": "done"})
        )
        # Orchestrators (have peers) return TerminationSignal when they produce a
        # final answer — the GroupExecutor uses this to know the collaboration is done.
        if ctx.peers:
            return TerminationSignal(result=output, reason="done")
        return output

    # ── Internal tool-use loop ────────────────────────────────────────────────

    async def _llm_loop(
        self,
        user_message: str,
        callables: list[Skill],   # bundled / marketplace / peer-wrapping skills
        run_id: str,
        emit,
        max_steps: int = _DEFAULT_MAX_STEPS,
        task_id: str = "",
        agent_id: str | None = None,
    ) -> AgentOutput:
        from app.budget.tracker import BudgetExceeded, check_budget, record_usage

        history: list[Message] = []
        first_turn = True
        steps = 0
        tool_error_counts: dict[str, int] = {}
        disabled_tools: set[str] = set()

        # ── Reasoning pass (optional) ────────────────────────────────────────
        if self.reasoning and user_message:
            await emit(RunEventData(
                run_id=run_id, seq=0, type=RunEventType.MESSAGE,
                agent=self.name,
                payload={"content": "[Thinking...]", "tool_calls": 0},
            ))
            reasoning_prompt = (
                "Think step by step. Briefly plan:\n"
                "1. What is being asked?\n"
                "2. Which tools to use and in what order?\n"
                "3. What does good output look like?\n\n"
                "Be concise — max 200 words."
            )
            think_response = await model_client.complete(
                model=self.model,
                system=self.system_prompt + "\n\n" + reasoning_prompt,
                history=[],
                tools=[],
                user_message=user_message,
            )
            await record_usage(
                run_id=run_id, agent_name=self.name,
                model=think_response.model or self.model,
                input_tokens=think_response.input_tokens,
                output_tokens=think_response.output_tokens,
            )
            await emit(RunEventData(
                run_id=run_id, seq=0, type=RunEventType.MESSAGE,
                agent=self.name,
                payload={"content": f"[Reasoning]\n{think_response.content}", "tool_calls": 0},
            ))
            # Inject reasoning into the user message so the conversation starts
            # with one user turn. Faking an assistant turn here breaks providers
            # (e.g. Anthropic via Azure) that reject histories ending in assistant.
            user_message = (
                f"{user_message}\n\n"
                f"---\n[Your prior planning notes]\n{think_response.content}\n"
                f"---\nNow execute the task."
            )

        while steps < max_steps:
            # Check budget before each LLM call
            if task_id:
                try:
                    await check_budget(run_id, task_id, agent_id)
                except BudgetExceeded as exc:
                    logger.warning("Budget exceeded for run %s: %s", run_id, exc.message)
                    return AgentOutput(
                        content=f"[Run stopped: {exc.message}]",
                        agent_name=self.name,
                        model_used=self.model,
                    )

            # Filter out disabled tools so the LLM stops trying them
            # disabled_tools tracks wire_names (what the LLM returns)
            active_callables = [
                c for c in callables
                if getattr(c, "wire_name", c.name) not in disabled_tools
            ]

            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            system = (
                f"Today's date: {today}\n\n"
                + self.system_prompt
                + "\n\nUse your tools and judgment to complete the request well. "
                "You may take initiative on intermediate steps — choosing which "
                "tool fits, retrying with different parameters, or following up "
                "on partial results — but stay within the scope of what was asked."
            )
            response = await model_client.complete(
                model=self.model,
                system=system,
                history=_trim_old_tool_results(history),
                tools=active_callables,
                user_message=user_message if first_turn else "",
            )
            first_turn = False
            steps += 1

            # Record token usage
            await record_usage(
                run_id=run_id,
                agent_name=self.name,
                model=response.model or self.model,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )

            await emit(RunEventData(
                run_id=run_id, seq=steps, type=RunEventType.MESSAGE,
                agent=self.name,
                payload={"content": response.content, "tool_calls": len(response.tool_calls)},
            ))

            if not response.tool_calls:
                return AgentOutput(
                    content=response.content,
                    agent_name=self.name,
                    model_used=response.model,
                    metadata={"input_tokens": response.input_tokens,
                               "output_tokens": response.output_tokens},
                )

            # Append assistant turn with tool calls
            history.append(Message(
                role="assistant",
                content=response.content,
                tool_calls=response.tool_calls,
            ))

            # Execute all tool calls in this turn
            results = await self._execute_tool_calls(
                response.tool_calls, callables, run_id, emit, steps
            )

            # Track errors and disable tools that keep failing
            for tc, result in zip(response.tool_calls, results):
                if result.is_error:
                    tool_error_counts[tc.name] = tool_error_counts.get(tc.name, 0) + 1
                    if tool_error_counts[tc.name] >= _MAX_TOOL_ERRORS:
                        disabled_tools.add(tc.name)
                        result.content += (
                            f"\n\n[SYSTEM: {tc.name} has been disabled after "
                            f"{_MAX_TOOL_ERRORS} consecutive errors. "
                            "Do NOT attempt to call it again. "
                            "Complete your task with the information you have.]"
                        )
                        logger.warning("Disabled tool %r for agent %s after %d errors",
                                       tc.name, self.name, _MAX_TOOL_ERRORS)
                else:
                    tool_error_counts.pop(tc.name, None)  # reset on success

            history.append(Message(role="tool_results", results=results))

        logger.warning("%s hit max_steps=%d — returning last content", self.name, max_steps)
        last_content = history[-2].content if len(history) >= 2 else ""
        return AgentOutput(content=last_content, agent_name=self.name, model_used=self.model)

    async def _execute_tool_calls(
        self,
        tool_calls: list[ToolCall],
        callables: list,
        run_id: str,
        emit,
        base_seq: int,
    ) -> list[ToolResult]:
        results: list[ToolResult] = []
        for i, tc in enumerate(tool_calls):
            await emit(RunEventData(
                run_id=run_id, seq=base_seq * 100 + i, type=RunEventType.TOOL_CALL,
                agent=self.name, payload={"tool": tc.name, "args": tc.args},
            ))
            result = await _call_callable(tc, callables)
            await emit(RunEventData(
                run_id=run_id, seq=base_seq * 100 + i + 1, type=RunEventType.TOOL_RESULT,
                agent=self.name,
                payload={"tool": tc.name, "result": result.content[:500], "error": result.is_error},
            ))
            results.append(result)
        return results


# ── Helpers ───────────────────────────────────────────────────────────────────

def _trim_old_tool_results(
    history: list[Message],
    keep: int = _KEEP_FULL_TOOL_RESULTS,
) -> list[Message]:
    """Return a shallow copy of `history` with old tool_results summarised.

    The last `keep` tool_results messages are kept in full — the LLM still
    needs recent tool output to reason. Older ones have each ToolResult.content
    replaced with a short preview + length marker so the model knows the call
    happened and roughly what it returned, but doesn't re-ingest the full body
    on every subsequent step.

    Returns a new list; the input is not mutated (the executor still writes
    the full event stream to the DB from the untrimmed history).
    """
    tr_positions = [i for i, m in enumerate(history) if m.role == "tool_results"]
    if len(tr_positions) <= keep:
        return history

    to_trim = set(tr_positions[:-keep])
    out: list[Message] = []
    for i, m in enumerate(history):
        if i in to_trim and m.role == "tool_results":
            trimmed = [
                ToolResult(
                    tool_call_id=tr.tool_call_id,
                    content=_summarise_tool_result(tr.content, tr.is_error),
                    is_error=tr.is_error,
                )
                for tr in m.results
            ]
            out.append(Message(role="tool_results", results=trimmed))
        else:
            out.append(m)
    return out


def _summarise_tool_result(content: str, is_error: bool) -> str:
    if len(content) <= 200:
        return content  # already cheap, leave alone
    preview = content[: _SUMMARY_PREVIEW_CHARS].replace("\n", " ").strip()
    tag = "error" if is_error else "result"
    return f"[older {tag}, {len(content)} chars elided] {preview}..."


def _build_dag_prompt(ctx: DAGContext) -> str:
    import json as _json

    parts = []
    if ctx.task_description:
        parts.append(ctx.task_description)

    # Handle special keys from pipeline steps
    inputs = dict(ctx.inputs) if ctx.inputs else {}
    prev = inputs.pop("previous_output", None)
    if prev:
        parts.append(f"---\nprevious_output:\n{prev}")

    # Render remaining inputs naturally
    if inputs:
        # If there's only simple string values, render as key: value pairs
        # instead of raw JSON (more natural for the LLM)
        simple = all(isinstance(v, (str, int, float, bool)) for v in inputs.values())
        if simple:
            lines = ["---\nTask parameters:"]
            for k, v in inputs.items():
                lines.append(f"- {k}: {v}")
            parts.append("\n".join(lines))
        else:
            parts.append(f"Task inputs:\n{_json.dumps(inputs, indent=2)}")

    if ctx.upstream:
        parts.append("Outputs from previous DAG nodes:")
        for node_name, output in ctx.upstream.items():
            parts.append(f"[{node_name}]\n{output.content}")
    return "\n\n".join(parts) if parts else "Begin."


async def _call_callable(tc: ToolCall, callables: list[Skill]) -> ToolResult:
    """Resolve a tool_call against the agent's available skills and execute.

    Every callable visible to the LLM is a Skill — bundled, marketplace, or a
    PeerCallSkill wrapping a peer agent. The LLM returns the sanitized
    wire_name, so we match that first and fall back to the raw name.
    """
    for c in callables:
        if c.wire_name == tc.name or c.name == tc.name:
            try:
                content = await c.execute(**tc.args)
                return ToolResult(tool_call_id=tc.id, content=str(content))
            except Exception as exc:
                return ToolResult(tool_call_id=tc.id, content=str(exc), is_error=True)
    return ToolResult(tool_call_id=tc.id, content=f"Unknown skill: {tc.name!r}", is_error=True)


def _PeerCallTool(agent_name: str, call_fn) -> Skill:
    """Wrap a peer agent's callable as a Skill so the orchestrator's LLM can
    invoke it through the same tool-call surface as any other skill."""

    async def _execute(task: str, context: str = "") -> str:
        output: AgentOutput = await call_fn(task=task, context=context)
        return output.content

    return Skill(
        name=f"call_{agent_name}",
        description=f"Delegate a sub-task to the {agent_name} agent and receive its response.",
        parameters={
            "type": "object",
            "properties": {
                "task": {
                    "type": "string",
                    "description": "The specific task or question for the agent.",
                },
                "context": {
                    "type": "string",
                    "description": "Relevant background the agent needs to complete its task.",
                },
            },
            "required": ["task"],
        },
        _execute=_execute,
    )
