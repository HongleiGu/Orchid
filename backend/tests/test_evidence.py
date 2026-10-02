"""Evidence contract — schema + Layer-2 aggregation (OR-55/56).

Runs on StubNLI, so no model download and no GPU: these test the *logic* that
turns entailment results into verdicts. The real model is exercised by the eval
harness (app/evidence/eval), not here.
"""
from __future__ import annotations

import json

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


# ── LLM-judge baseline (the thing the contract is measured against) ───────────

def test_judge_parse_reads_json_verdict_and_reason():
    from app.evidence.judge import _parse
    v = _parse('{"supported": true, "reason": "the report gives the figure"}')
    assert v.supported is True and "report" in v.reason
    v = _parse('nonsense before {"supported": false, "reason": "off topic"} after')
    assert v.supported is False and v.reason == "off topic"


def test_judge_parse_falls_back_to_yes_no_scan():
    from app.evidence.judge import _parse
    assert _parse("Yes, clearly supported.").supported is True
    assert _parse("No — the source is unrelated.").supported is False


def test_llm_judge_uses_injected_completion():
    from app.evidence.judge import LLMJudge
    calls = []

    def fake(system, user):
        calls.append(user)
        return '{"supported": true, "reason": "cites a 2025 report"}'

    v = LLMJudge(model="x", complete_fn=fake).judge("市场规模达到五十亿元", "根据报告……")
    assert v.supported is True and calls, "the claim and passage must reach the model"


def test_stub_judge_shows_authority_bias():
    """The stub reproduces the failure the eval measures: a fabricated citation
    that merely looks authoritative is accepted."""
    from app.evidence.judge import StubJudge
    j = StubJudge()
    # unrelated but authoritative-sounding (has a number) → wrongly accepted
    assert j.judge("The pet-food market reached 15B yuan",
                   "The coffee market reached 15B yuan in 2025.").supported is True
    # no authority signal → not accepted
    assert j.judge("Demand is large", "the weather was mild").supported is False


# ── claim decomposition (the recall fix for Layer-2) ──────────────────────────

def _fixed_decomposer(atoms):
    """An LLMDecomposer whose LLM call is stubbed to return a fixed atom list."""
    from app.evidence.decompose import LLMDecomposer
    payload = json.dumps(atoms)
    return LLMDecomposer(model="x", complete_fn=lambda s, u: payload)


def test_decompose_parse_reads_text_and_verifiable():
    d = _fixed_decomposer([{"text": "users want offline mode", "verifiable": True},
                           {"text": "it is revolutionary", "verifiable": False}])
    atoms = d.decompose("whatever")
    assert [a.text for a in atoms] == ["users want offline mode", "it is revolutionary"]
    assert [a.verifiable for a in atoms] == [True, False]


def test_stub_decomposer_splits_clauses():
    from app.evidence.decompose import StubDecomposer
    atoms = StubDecomposer().decompose("Users want offline mode and the price is 99 yuan")
    assert len(atoms) == 2 and all(a.verifiable for a in atoms)


def test_decomposition_rescues_an_abstractive_claim():
    """The crux of the recall fix: an opinion-laden claim whose *factual* atom is
    entailed is SUPPORTED even though the whole sentence is not entailed, because
    the opinion atom is dropped rather than graded."""
    from app.evidence.verify import verify_claim, verify_claim_decomposed
    statement = "Users frequently request offline mode and it is a game-changing feature"
    passage = "Reviews show users frequently request offline mode."
    c = claim(statement, passage)
    # Whole-sentence NLI (stub) fails: the sentence is not contained in the passage.
    assert verify_claim(claim(statement, passage), NLI).verdict != Verdict.SUPPORTED
    # Decomposed: factual atom entailed, opinion atom not graded → SUPPORTED.
    d = _fixed_decomposer([{"text": "Users frequently request offline mode", "verifiable": True},
                           {"text": "offline mode is a game-changing feature", "verifiable": False}])
    out = verify_claim_decomposed(c, NLI, d)
    assert out.verdict == Verdict.SUPPORTED
    assert len(out.atoms) == 2 and sum(a.verifiable for a in out.atoms) == 1


def test_decomposition_still_rejects_a_mis_citation():
    """Decomposition must not leak support: an on-topic-but-unrelated passage
    entails none of the atoms → UNSUPPORTED (the property we must preserve)."""
    from app.evidence.verify import verify_claim_decomposed
    c = claim("The pet-food market reached 15 billion yuan in 2025",
              "The weather in Beijing was mild throughout the spring.")
    d = _fixed_decomposer([{"text": "The pet-food market reached 15 billion yuan in 2025", "verifiable": True}])
    assert verify_claim_decomposed(c, NLI, d).verdict != Verdict.SUPPORTED


def test_decomposition_with_no_verifiable_atoms_falls_back():
    from app.evidence.verify import verify_claim_decomposed
    c = claim("This product is wonderful", "Reviews show users frequently request offline mode.")
    d = _fixed_decomposer([{"text": "it is wonderful", "verifiable": False}])
    # No gradeable atom → whole-statement fallback, which the stub cannot entail.
    assert verify_claim_decomposed(c, NLI, d).verdict != Verdict.SUPPORTED


def test_faithfulness_drops_atoms_the_statement_does_not_entail():
    """Decomposition-faithfulness (A): an atom the ORIGINAL statement does not
    entail was introduced by the decomposer and must not be graded."""
    from app.evidence.verify import verify_claim_decomposed
    c = claim("Users frequently request offline mode",
              "Reviews show users frequently request offline mode.")
    d = _fixed_decomposer([{"text": "Users frequently request offline mode", "verifiable": True},
                           {"text": "The CEO resigned in 2026", "verifiable": True}])  # fabricated
    out = verify_claim_decomposed(c, NLI, d)
    graded = [a.text for a in out.atoms if a.verifiable]
    assert "Users frequently request offline mode" in graded
    assert "The CEO resigned in 2026" not in graded          # dropped as unfaithful
    assert out.verdict == Verdict.SUPPORTED


def test_all_atoms_unfaithful_backs_off_to_whole_sentence():
    from app.evidence.verify import verify_claim_decomposed
    stmt = "Users frequently request offline mode"
    d = _fixed_decomposer([{"text": "The CEO resigned in 2026", "verifiable": True}])  # all fabricated
    # back-off to whole sentence, which the source entails -> SUPPORTED
    c = claim(stmt, "Reviews show users frequently request offline mode.")
    assert verify_claim_decomposed(c, NLI, d).verdict == Verdict.SUPPORTED
