"""Run-trace verbosity (OR-35)."""
from __future__ import annotations

import pytest

from app.api.verbosity import (
    Verbosity,
    ceiling_for_profile,
    effective,
    filter_events,
    redact,
    visible,
)


class _Event:
    """Stand-in for a RunEvent row / a decoded stream frame."""

    def __init__(self, type_, payload=None):
        self.type = type_
        self.payload = payload or {}


# ── Level ceiling ─────────────────────────────────────────────────────────────

def test_run_only_profile_caps_at_info():
    """debug is the workflow itself, and the workflow is the product."""
    assert ceiling_for_profile("app") is Verbosity.INFO
    assert effective(Verbosity.DEBUG, "app") is Verbosity.INFO
    assert effective(Verbosity.INFO, "app") is Verbosity.INFO
    assert effective(Verbosity.SUMMARY, "app") is Verbosity.SUMMARY


def test_full_profile_allows_debug():
    assert ceiling_for_profile("full") is Verbosity.DEBUG
    assert effective(Verbosity.DEBUG, "full") is Verbosity.DEBUG


# ── Visibility by level ───────────────────────────────────────────────────────

@pytest.mark.parametrize("etype", ["agent_start", "agent_end", "terminated", "error"])
def test_structural_events_show_at_summary(etype):
    assert visible(etype, {}, Verbosity.SUMMARY)


@pytest.mark.parametrize("etype", ["tool_call", "tool_result", "contract_check"])
def test_tool_activity_needs_info(etype):
    assert not visible(etype, {}, Verbosity.SUMMARY)
    assert visible(etype, {}, Verbosity.INFO)


@pytest.mark.parametrize("etype", ["message", "collab_route"])
def test_agent_output_and_routing_need_debug(etype):
    """These are the workflow's substance, so they never appear under `app`."""
    assert not visible(etype, {}, Verbosity.SUMMARY)
    assert not visible(etype, {}, Verbosity.INFO)
    assert visible(etype, {}, Verbosity.DEBUG)


def test_unknown_event_types_default_to_debug():
    """Deny-by-default again: a new event type is hidden until classified."""
    assert not visible("some_new_event", {}, Verbosity.INFO)
    assert visible("some_new_event", {}, Verbosity.DEBUG)


# ── Errors are never hidden ───────────────────────────────────────────────────

def test_errors_show_at_every_level():
    """The 'don't make me run it again' case."""
    assert visible("error", {"error": "boom"}, Verbosity.SUMMARY)


def test_a_failing_message_event_surfaces_despite_needing_debug():
    """A message event is debug-only, but one carrying an error still appears —
    otherwise the failure would be invisible at info."""
    assert visible("message", {"error": "rate limited"}, Verbosity.INFO)


def test_failure_keeps_diagnostics_but_not_content():
    """The trap this avoids: escalating to debug on error would let anyone who
    can induce a failure read the prompts."""
    out = redact("message", {
        "content": "the system prompt and full agent reply",
        "error": "HTTP 403 from web_reader",
        "status_code": 403,
    }, Verbosity.INFO)

    assert out["error"] == "HTTP 403 from web_reader"
    assert out["status_code"] == 403
    assert "content" not in out
    assert out["_withheld"] == ["content"]


# ── Redaction ─────────────────────────────────────────────────────────────────

def test_debug_returns_the_payload_untouched():
    payload = {"content": "x", "arguments": {"q": "y"}}
    assert redact("message", payload, Verbosity.DEBUG) == payload


def test_tool_name_survives_but_arguments_do_not():
    """Tool names are the published skill list; the arguments show how the
    workflow drives them."""
    out = redact("tool_call", {"tool": "web_search", "arguments": {"q": "内部提示词"}},
                 Verbosity.INFO)
    assert out["tool"] == "web_search"
    assert "arguments" not in out


def test_non_sensitive_keys_pass_through():
    out = redact("agent_end", {"status": "ok", "duration_ms": 1234}, Verbosity.INFO)
    assert out == {"status": "ok", "duration_ms": 1234}


# ── List filtering ────────────────────────────────────────────────────────────

def test_filter_drops_and_redacts_in_one_pass():
    events = [
        _Event("agent_start", {"agent": "cmb_verifier"}),
        _Event("message", {"content": "secret prompt output"}),
        _Event("tool_call", {"tool": "market_data", "arguments": {"code": "600519"}}),
        _Event("error", {"error": "quote API timeout"}),
    ]
    kept = filter_events(events, Verbosity.INFO)

    assert [e.type for e in kept] == ["agent_start", "tool_call", "error"]
    assert "arguments" not in kept[1].payload
    assert kept[1].payload["tool"] == "market_data"
    assert kept[2].payload["error"] == "quote API timeout"


def test_debug_keeps_everything():
    events = [_Event("message", {"content": "x"}), _Event("collab_route", {"to": "y"})]
    assert len(filter_events(events, Verbosity.DEBUG)) == 2
