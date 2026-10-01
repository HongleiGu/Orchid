"""Layer-2 grounding contract check routed into the DAG engine (OR-58).

Uses the evidence module's StubNLI so no model is downloaded: a claim is
"grounded" when the upstream evidence literally contains it. This tests the
wiring and aggregation in dag._run_grounding_check, not the NLI model (that is
measured by the evidence eval harness).
"""
from __future__ import annotations

import pytest

from app.core import dag
from app.core.types import AgentOutput
from app.evidence.nli import StubNLI


@pytest.fixture(autouse=True)
def _stub_verifier():
    dag.set_grounding_verifier(StubNLI())
    dag.set_grounding_decomposer(None)  # force whole-sentence path (no LLM in tests)
    yield
    dag.set_grounding_verifier(None)
    dag._grounding_decomposer_resolved = False


def _out(content: str) -> AgentOutput:
    return AgentOutput(content=content, agent_name="writer")


async def test_grounded_claims_pass():
    out = _out("The market grew 40 percent in 2026. Demand for offline mode is rising.")
    upstream = {"research": _out(
        "Reports show the market grew 40 percent in 2026. "
        "Reviews show demand for offline mode is rising among users."
    )}
    res = await dag._run_grounding_check(out, upstream, {"min_grounded": 0.8}, index=0)
    assert res["status"] == "pass", res["reason"]


async def test_ungrounded_claim_fails_and_is_named():
    out = _out(
        "The market grew 40 percent in 2026. "
        "The company secretly plans to acquire three competitors next quarter."
    )
    upstream = {"research": _out("Reports show the market grew 40 percent in 2026.")}
    res = await dag._run_grounding_check(out, upstream, {"min_grounded": 0.8}, index=0)
    assert res["status"] == "fail"
    assert "acquire three competitors" in res["reason"]


async def test_skips_gracefully_without_a_verifier():
    dag.set_grounding_verifier(None)          # force unresolved
    dag._grounding_verifier_resolved = True   # and pretend resolution found nothing
    try:
        res = await dag._run_grounding_check(_out("Any claim at all here."),
                                             {"r": _out("evidence")}, {}, index=0)
        assert res["status"] == "pass" and "skipped" in res["reason"].lower()
    finally:
        dag._grounding_verifier_resolved = False


async def test_no_upstream_evidence_skips():
    res = await dag._run_grounding_check(_out("A claim with no evidence to check."),
                                         {}, {}, index=0)
    assert res["status"] == "pass" and "skipped" in res["reason"].lower()
