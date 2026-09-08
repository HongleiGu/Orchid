"""Per-run cost (OR-36) and the pricing table behind it.

The aggregation helpers themselves need a database and were verified against a
real Postgres; what is unit-testable is the pricing that feeds them, which is
where a wrong number would come from.
"""
from __future__ import annotations

import pytest

from app.api.v1.runs import AgentCost, RunCost
from app.budget import pricing
from app.budget.pricing import estimate_cost, is_priced


@pytest.fixture(autouse=True)
def _reset_warning_state():
    pricing._warned_unknown.clear()
    yield
    pricing._warned_unknown.clear()


# ── Pricing ───────────────────────────────────────────────────────────────────

def test_deepseek_is_priced():
    """It is the default model for this deployment; the fallback would report
    roughly 3-4x the real cost on an input-heavy run."""
    assert is_priced("deepseek/deepseek-chat")
    assert is_priced("deepseek/deepseek-reasoner")


def test_deepseek_costs_far_less_than_the_fallback():
    listed = estimate_cost("deepseek/deepseek-chat", 190_000, 13_000)
    fallback = estimate_cost("some/unlisted-model", 190_000, 13_000)
    assert listed < fallback / 3


def test_unknown_model_warns_once(caplog):
    """Once per model, not once per call — a run makes dozens."""
    with caplog.at_level("WARNING"):
        for _ in range(5):
            estimate_cost("mystery/model", 1000, 100)
    assert caplog.text.count("No pricing for model") == 1
    assert "mystery/model" in caplog.text


def test_each_unknown_model_warns_separately(caplog):
    with caplog.at_level("WARNING"):
        estimate_cost("mystery/one", 10, 10)
        estimate_cost("mystery/two", 10, 10)
    assert caplog.text.count("No pricing for model") == 2


def test_known_model_does_not_warn(caplog):
    with caplog.at_level("WARNING"):
        estimate_cost("deepseek/deepseek-chat", 10_000, 1_000)
    assert "No pricing" not in caplog.text


def test_zero_tokens_costs_nothing():
    assert estimate_cost("deepseek/deepseek-chat", 0, 0) == 0.0


def test_input_and_output_are_priced_separately():
    """Output is dearer; swapping the two must change the total."""
    a = estimate_cost("deepseek/deepseek-chat", 100_000, 0)
    b = estimate_cost("deepseek/deepseek-chat", 0, 100_000)
    assert b > a


# ── Shapes ────────────────────────────────────────────────────────────────────

def test_run_cost_defaults_to_zero():
    """A run with no LLM calls yet must report zero, not null — the catalog UI
    renders this on every row."""
    c = RunCost()
    assert (c.cost_usd, c.input_tokens, c.output_tokens, c.llm_calls) == (0.0, 0, 0, 0)


def test_agent_cost_carries_the_totals_plus_attribution():
    a = AgentCost(agent="cmb_verifier", model="deepseek/deepseek-chat",
                  cost_usd=0.18, input_tokens=150_000, output_tokens=10_000, llm_calls=2)
    assert a.agent == "cmb_verifier"
    assert a.cost_usd == 0.18
    # It is a RunCost, so the same renderer handles both.
    assert isinstance(a, RunCost)
