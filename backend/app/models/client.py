"""
Unified LLM client backed by LiteLLM.

All messages use the OpenAI wire format (which LiteLLM normalises to for every
provider).  The caller works purely with our internal types (Message, ToolCall,
ToolResult, AgentOutput) and never touches provider SDKs directly.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field

import litellm
from litellm import acompletion

from app.core.types import Message, ToolCall, messages_to_openai

logger = logging.getLogger(__name__)

# Transient provider errors that should not sink a long multi-call run. LiteLLM
# retries some of these internally, but sporadic malformed/empty responses
# (e.g. OpenRouter returning non-JSON) still surface here, so we add a short
# outer retry with backoff on top.
_TRANSIENT_LLM_ERRORS = tuple(
    exc for exc in (
        getattr(litellm, "APIError", None),
        getattr(litellm, "APIConnectionError", None),
        getattr(litellm, "Timeout", None),
        getattr(litellm, "RateLimitError", None),
        getattr(litellm, "InternalServerError", None),
        getattr(litellm, "ServiceUnavailableError", None),
    ) if isinstance(exc, type)
) or (Exception,)


async def _acompletion_with_retry(attempts: int = 3, **kwargs):
    delay = 2.0
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return await acompletion(**kwargs)
        except _TRANSIENT_LLM_ERRORS as exc:
            last_exc = exc
            if attempt == attempts:
                break
            logger.warning(
                "Transient LLM error (attempt %d/%d), retrying in %.0fs: %s",
                attempt, attempts, delay, exc,
            )
            await asyncio.sleep(delay)
            delay *= 2
    assert last_exc is not None
    raise last_exc


def _configure_litellm() -> None:
    from app.config import get_settings

    s = get_settings()
    litellm.drop_params = s.litellm_drop_params
    litellm.request_timeout = s.litellm_request_timeout
    litellm.num_retries = s.litellm_max_retries
    if s.openai_api_base:
        litellm.api_base = s.openai_api_base  # Azure / custom base URL


@dataclass
class ModelResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0


class ModelClient:
    """Thin async wrapper around LiteLLM `acompletion`."""

    def __init__(self) -> None:
        _configure_litellm()

    async def complete(
        self,
        model: str,
        system: str,
        history: list[Message],
        tools: list,          # list[Skill] — anything with .to_openai_spec()
        user_message: str = "",
    ) -> ModelResponse:
        """
        Send a completion request.

        `history` is the ongoing conversation (assistant + tool_results turns).
        `user_message` is appended as the next user turn when provided (first
        call per invocation).  Subsequent calls within the same tool-use loop
        should include the user_message only on the first turn and pass the
        growing history thereafter.
        """
        openai_messages: list[dict] = [{"role": "system", "content": system}]
        openai_messages.extend(messages_to_openai(history))
        if user_message:
            openai_messages.append({"role": "user", "content": user_message})

        tool_specs = [t.to_openai_spec() for t in tools] if tools else None

        kwargs: dict = {"model": model, "messages": openai_messages}
        if tool_specs:
            kwargs["tools"] = tool_specs

        try:
            resp = await _acompletion_with_retry(**kwargs)
        except Exception as exc:
            logger.error("LiteLLM completion error for model %r: %s", model, exc)
            raise

        choice = resp.choices[0]
        msg = choice.message
        content: str = msg.content or ""

        tool_calls: list[ToolCall] = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, args=args))

        usage = getattr(resp, "usage", None)
        return ModelResponse(
            content=content,
            tool_calls=tool_calls,
            model=resp.model or model,
            input_tokens=getattr(usage, "prompt_tokens", 0),
            output_tokens=getattr(usage, "completion_tokens", 0),
        )


# Module-level singleton
model_client = ModelClient()
