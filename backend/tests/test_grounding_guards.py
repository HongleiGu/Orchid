"""Numeric guard (B): a claim's numbers must appear in the evidence (OR-58).

Guards the documented NLI blind spot — insensitivity to single-digit numeric
precision ("15B" vs "16B") in otherwise near-identical context.
"""
from __future__ import annotations

from app.evidence.grounding import ground_claims, numbers_supported
from app.evidence.nli import StubNLI


def test_numbers_supported():
    assert numbers_supported("market reached 15 billion", "the market reached 15 billion in 2025")
    assert not numbers_supported("market reached 15 billion", "the market reached 16 billion")
    assert numbers_supported("no digits in this claim", "any evidence at all")


def test_numeric_guard_demotes_wrong_number_even_when_nli_entails():
    nli = StubNLI()  # entails by token overlap -> near-identical sentences "match"
    wrong = ground_claims(nli, ["The market grew 40 percent in 2026."],
                          ["The market grew 50 percent in 2026."], min_grounded=0.8)
    assert wrong["fraction"] == 0.0            # 40 not in evidence -> demoted

    right = ground_claims(nli, ["The market grew 40 percent in 2026."],
                         ["The market grew 40 percent in 2026."], min_grounded=0.8)
    assert right["fraction"] == 1.0            # number present -> grounded


def test_ground_claims_handles_no_evidence():
    # empty/emptied context must not crash -> claim simply ungrounded (regression)
    res = ground_claims(StubNLI(), ["a claim with no evidence to check"], [], min_grounded=0.8)
    assert res["fraction"] == 0.0 and res["details"][0]["grounded"] is False


def test_numeric_guard_can_be_disabled():
    nli = StubNLI()
    res = ground_claims(nli, ["The market grew 40 percent in 2026."],
                        ["The market grew 50 percent in 2026."], min_grounded=0.8,
                        numeric_guard=False)
    assert res["fraction"] == 1.0              # guard off -> NLI's (wrong) entailment stands
