"""Run-trace verbosity (OR-35).

Everything is always recorded — run_events keeps the full trace regardless — and
verbosity governs only what a caller is shown. So switching levels never
requires re-running, which is the point.

Three levels, in the logging idiom:

    summary  structural progress: which stage started and ended, and how it
             finished. Enough to render a progress view.
    info     + tool calls by name, contract checks, timings. Enough to see what
             the workflow is doing.
    debug    + message content, prompts, tool arguments, inter-agent routing.
             The actual workflow implementation.

The profile sets a ceiling. Under PRODUCT_PROFILE=app the maximum is `info`,
because `debug` is the workflow itself and the workflow is the product.

Errors are never hidden. A failed run always shows its error events and the
tool failures around them, at any level — that is the "don't make me run it
again" case. It reveals diagnostics, not internals: what failed, where, and
what the tool said. Escalating all the way to debug on error would turn any
input that induces a failure into a way to extract the prompts.
"""
from __future__ import annotations

from enum import Enum

from app.core.types import RunEventType


class Verbosity(str, Enum):
    SUMMARY = "summary"
    INFO = "info"
    DEBUG = "debug"


_ORDER = {Verbosity.SUMMARY: 0, Verbosity.INFO: 1, Verbosity.DEBUG: 2}

# Lowest level at which each event type appears at all.
_MIN_LEVEL: dict[str, Verbosity] = {
    RunEventType.AGENT_START.value: Verbosity.SUMMARY,
    RunEventType.AGENT_END.value: Verbosity.SUMMARY,
    RunEventType.TERMINATED.value: Verbosity.SUMMARY,
    RunEventType.ERROR.value: Verbosity.SUMMARY,
    RunEventType.CONTRACT_CHECK.value: Verbosity.INFO,
    RunEventType.TOOL_CALL.value: Verbosity.INFO,
    RunEventType.TOOL_RESULT.value: Verbosity.INFO,
    # Agent output and inter-agent routing are the workflow's substance.
    RunEventType.MESSAGE.value: Verbosity.DEBUG,
    RunEventType.COLLAB_ROUTE.value: Verbosity.DEBUG,
}

# Payload keys withheld below debug. Tool *names* are fine at info — they are
# the published skill list — but the arguments show how the workflow drives
# them, which is not.
_DEBUG_ONLY_KEYS = frozenset({
    "content", "prompt", "system_prompt", "messages", "arguments", "args",
    "reasoning", "plan",
})

# Keys that survive at any level on a failing event, so a failure is
# actionable without re-running.
_DIAGNOSTIC_KEYS = frozenset({"error", "error_type", "status", "status_code", "reason"})


def ceiling_for_profile(profile: str) -> Verbosity:
    """The highest level this deployment will serve."""
    return Verbosity.INFO if profile == "app" else Verbosity.DEBUG


def effective(requested: Verbosity, profile: str) -> Verbosity:
    ceiling = ceiling_for_profile(profile)
    return requested if _ORDER[requested] <= _ORDER[ceiling] else ceiling


def _is_failure(event_type: str, payload: dict) -> bool:
    return event_type in (RunEventType.ERROR.value, RunEventType.TERMINATED.value) or bool(
        payload.get("error")
    )


def visible(event_type: str, payload: dict, level: Verbosity) -> bool:
    """Whether an event appears at all."""
    if _is_failure(event_type, payload):
        return True                      # errors are never hidden
    minimum = _MIN_LEVEL.get(event_type, Verbosity.DEBUG)
    return _ORDER[level] >= _ORDER[minimum]


def redact(event_type: str, payload: dict, level: Verbosity) -> dict:
    """Strip payload keys above the level, keeping diagnostics on failures."""
    if level is Verbosity.DEBUG:
        return payload

    failure = _is_failure(event_type, payload)
    out = {}
    for key, value in payload.items():
        if key not in _DEBUG_ONLY_KEYS:
            out[key] = value
        elif failure and key in _DIAGNOSTIC_KEYS:
            out[key] = value
    if failure:
        # Say what was withheld, so a support conversation is not a guessing game.
        withheld = sorted(set(payload) & _DEBUG_ONLY_KEYS)
        if withheld:
            out["_withheld"] = withheld
    return out


def filter_events(events: list, level: Verbosity) -> list:
    """Apply visibility and redaction to a list of event-like objects.

    Takes anything with .type and .payload, so it serves both the stored rows
    and the live stream.
    """
    kept = []
    for e in events:
        etype = e.type if isinstance(e.type, str) else getattr(e.type, "value", str(e.type))
        payload = e.payload or {}
        if not visible(etype, payload, level):
            continue
        e.payload = redact(etype, payload, level)
        kept.append(e)
    return kept
