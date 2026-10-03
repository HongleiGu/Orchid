"""Argument verifier + router (research): warrant check + rebuttal search.

StubNLI = token-containment entailment (negation -> contradict). Enough to show
the distinguishing behaviour: a claim whose facts are all present but whose
INFERENCE does not hold is caught by the warrant, where flat NLI passes it.
"""
from __future__ import annotations

from app.evidence.argument import (
    Argument,
    StubArgumentMiner,
    verify_argument,
)
from app.evidence.grounding import ground_claims
from app.evidence.nli import StubNLI
from app.evidence.router import ClaimKind, Strength, classify_claim, verify_routed
from app.evidence.schema import Verdict

NLI = StubNLI()


# ── the money case: true facts, unwarranted conclusion ───────────────────────

def test_warrant_catches_unwarranted_conclusion_that_flat_nli_passes():
    claim = "The company revenue grew because the CEO resigned"
    evidence = ["Reports show the company revenue grew. The CEO resigned."]

    # flat whole-claim NLI: all content tokens are in the evidence -> it passes.
    flat = ground_claims(NLI, [claim], evidence, min_grounded=0.5)
    assert flat["details"][0]["grounded"] is True            # flat NLI says supported

    # argument verifier: ground ("CEO resigned") is present, but it does NOT entail
    # the claim ("revenue grew") -> warrant invalid -> NOT supported.
    arg = StubArgumentMiner().mine(claim)   # -> claim="...revenue grew", grounds=["the CEO resigned"]
    av = verify_argument(arg, evidence, NLI)
    assert av.warrant_valid is False
    assert av.verdict != Verdict.SUPPORTED                   # warrant caught what flat NLI missed


def test_valid_argument_is_supported():
    arg = Argument(claim="Users want offline mode",
                   grounds=["Users want offline mode and dark theme"])
    evidence = ["Reviews show users want offline mode and dark theme."]
    av = verify_argument(arg, evidence, NLI)
    assert all(av.grounds_grounded) and av.warrant_valid and not av.attacks
    assert av.verdict == Verdict.SUPPORTED


def test_rebuttal_in_evidence_refutes():
    arg = Argument(claim="The market grew 40 percent", grounds=["The market grew 40 percent"])
    evidence = ["The market did not grow 40 percent."]
    av = verify_argument(arg, evidence, NLI)
    assert any(a.kind == "rebut" for a in av.attacks)
    assert av.verdict == Verdict.REFUTED


def test_argument_graph_is_auditable():
    arg = Argument(claim="c", grounds=["g1"], warrant="w")
    g = verify_argument(arg, ["unrelated evidence"], NLI).graph()
    assert set(g) >= {"claim", "grounds", "warrant", "attacks", "verdict"}


# ── router ────────────────────────────────────────────────────────────────────

def test_classify_claim_kinds():
    assert classify_claim("2 + 2 = 4") == ClaimKind.FORMAL
    assert classify_claim("For all integers n, n squared is non-negative") == ClaimKind.FORMAL
    assert classify_claim("Revenue grew because the CEO resigned") == ClaimKind.ARGUMENTATIVE
    assert classify_claim("The capital of France is Paris") == ClaimKind.ATOMIC
    assert classify_claim("I think this is the best approach") == ClaimKind.OPINION


def test_router_argumentative_uses_argument_verifier():
    v = verify_routed("Revenue grew because the CEO resigned",
                      ["Reports show revenue grew. The CEO resigned."],
                      NLI, miner=StubArgumentMiner())
    assert v.kind == ClaimKind.ARGUMENTATIVE and v.strength == Strength.ARGUMENT
    assert v.verdict != Verdict.SUPPORTED          # warrant invalid


def test_router_atomic_falls_to_entailment():
    v = verify_routed("The capital of France is Paris",
                      ["The capital of France is Paris."], NLI)
    assert v.kind == ClaimKind.ATOMIC and v.strength == Strength.ENTAILMENT
    assert v.verdict == Verdict.SUPPORTED


def test_router_opinion_not_graded():
    v = verify_routed("I think this is the best approach", ["anything"], NLI)
    assert v.verdict == Verdict.UNCERTAIN and v.strength == Strength.NONE
