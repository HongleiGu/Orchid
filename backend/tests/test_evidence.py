"""Evidence contract — schema + Layer-2 aggregation (OR-55/56).

Runs on StubNLI, so no model download and no GPU: these test the *logic* that
turns entailment results into verdicts. The real model is exercised by the eval
harness (app/evidence/eval), not here.
"""
from __future__ import annotations

from app.evidence.nli import StubNLI
from app.evidence.schema import Claim, EntailmentLabel, Source, Stance, Verdict
from app.evidence.verify import verify_claim


def claim(statement: str, *passages: str, stance: Stance = Stance.SUPPORT) -> Claim:
    return Claim(statement=statement, stance=stance,
                 sources=[Source(passage=p, url=f"http://s/{i}") for i, p in enumerate(passages)])


NLI = StubNLI()


# ── the core property: attribution, not citation presence ─────────────────────

def test_a_source_that_entails_the_claim_supports_it():
    c = verify_claim(claim("The market grew 40 percent in 2026",
                           "Reports show the market grew 40 percent in 2026."), NLI)
    assert c.verdict == Verdict.SUPPORTED
    assert c.confidence >= 0.6


def test_a_fabricated_citation_does_not_support_the_claim():
    """The crux. A real-looking but unrelated source must NOT support the claim —
    this is exactly what an LLM judge gets wrong via authority bias."""
    c = verify_claim(claim("The market grew 40 percent in 2026",
                           "The weather in Beijing was mild throughout the spring."), NLI)
    assert c.verdict == Verdict.UNSUPPORTED
    assert c.best_entailment().label != EntailmentLabel.ENTAIL


def test_a_contradicting_source_refutes_the_claim():
    c = verify_claim(claim("The market grew 40 percent in 2026",
                           "The market did not grow 40 percent in 2026."), NLI)
    assert c.verdict == Verdict.REFUTED


def test_no_sources_means_unsupported_never_supported():
    c = verify_claim(Claim(statement="Demand is large"), NLI)
    assert c.verdict == Verdict.UNSUPPORTED
    assert c.confidence == 0.0


def test_the_strongest_signal_wins_when_sources_disagree():
    c = verify_claim(claim("Users want offline mode",
                           "Reviews say users want offline mode.",   # contains the claim
                           "The weather was mild."), NLI)            # neutral
    assert c.verdict == Verdict.SUPPORTED


# ── stance: a refute-claim is "supported evidence against the thesis" ─────────

def test_refute_stance_flips_the_verdict_meaning():
    # An entailed refute-claim means the evidence-against holds → REFUTED.
    c = verify_claim(claim("There is no demand for paid weather apps",
                           "There is no demand for paid weather apps, surveys find.",
                           stance=Stance.REFUTE), NLI)
    assert c.verdict == Verdict.REFUTED


# ── Chinese content (the model is multilingual; the stub is per-character) ────

def test_chinese_claim_supported_by_chinese_source():
    c = verify_claim(claim("市场规模达到五十亿元",
                           "根据报告，市场规模达到五十亿元。"), NLI)
    assert c.verdict == Verdict.SUPPORTED


def test_chinese_fabricated_citation_is_unsupported():
    c = verify_claim(claim("市场规模达到五十亿元",
                           "北京春季天气总体温和宜人。"), NLI)
    assert c.verdict == Verdict.UNSUPPORTED


# ── schema ────────────────────────────────────────────────────────────────────

def test_best_entailment_prefers_entail_then_score():
    c = verify_claim(claim("Users want offline mode",
                           "Users want offline mode.", "Unrelated text about cats."), NLI)
    best = c.best_entailment()
    assert best is not None and best.label == EntailmentLabel.ENTAIL
