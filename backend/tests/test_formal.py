"""Formal-verification layer (research): math router + Z3 engine + integration.

The Z3 tests inject a hand-written formalisation (so they test the solver + the
validity-by-refuting-the-negation logic, not the LLM autoformaliser). The router
is tested on its model-free heuristic. Needs the `formal` extra (z3-solver).
"""
from __future__ import annotations

import pytest

from app.evidence.formal import (
    FormalResult,
    StubFormalVerifier,
    Z3Verifier,
    is_math_claim,
)
from app.evidence.nli import StubNLI
from app.evidence.schema import Claim, Source, Verdict
from app.evidence.verify import verify_claim_formal

z3 = pytest.importorskip("z3")


# ── router ────────────────────────────────────────────────────────────────────

def test_heuristic_router_flags_math_and_passes_prose():
    assert is_math_claim("The sum of two even numbers is even", nli=None)[0] is True
    assert is_math_claim("For all integers x, x + 1 > x", nli=None)[0] is True
    assert is_math_claim("Users frequently request an offline mode", nli=None)[0] is False


# ── Z3 engine (validity by refuting the negation) ─────────────────────────────

_SMT = {
    "The sum of two even numbers is even": {
        "declarations": "",
        "claim": "(forall ((x Int) (y Int)) (=> (and (= (mod x 2) 0) (= (mod y 2) 0)) (= (mod (+ x y) 2) 0)))",
    },
    "For every integer x, x + 1 equals x": {
        "declarations": "",
        "claim": "(forall ((x Int)) (= (+ x 1) x))",
    },
}


def _fake_formalize(statement: str) -> str:
    import json
    return json.dumps(_SMT.get(statement, {"declarations": "", "claim": ""}))


def test_z3_proves_a_true_theorem():
    v = Z3Verifier(model="x", formalize_fn=_fake_formalize)
    r = v.verify("The sum of two even numbers is even")
    assert r.verdict == Verdict.SUPPORTED and r.engine == "z3"


def test_z3_refutes_a_false_claim_with_counterexample():
    v = Z3Verifier(model="x", formalize_fn=_fake_formalize)
    r = v.verify("For every integer x, x + 1 equals x")
    assert r.verdict == Verdict.REFUTED and "counterexample" in r.detail


def test_z3_abstains_when_not_formalizable():
    v = Z3Verifier(model="x", formalize_fn=lambda s: '{"declarations": "", "claim": ""}')
    assert v.verify("Colourless green ideas sleep furiously").verdict == Verdict.UNCERTAIN


def test_z3_abstains_on_malformed_smt_never_supports():
    v = Z3Verifier(model="x", formalize_fn=lambda s: '{"declarations": "", "claim": "(this is not smt"}')
    assert v.verify("whatever").verdict == Verdict.UNCERTAIN


# ── integration: router -> formal, with NLI fallback ──────────────────────────

def test_math_claim_gets_proof_level_verdict():
    c = Claim(statement="The sum of two even numbers is even")
    out = verify_claim_formal(c, nli=None, formal_verifier=StubFormalVerifier())
    assert out.verdict == Verdict.SUPPORTED and out.confidence == 1.0
    assert any(sc.kind == "formal:stub" for sc in out.structured_checks)


def test_non_math_claim_falls_back_to_nli():
    c = Claim(statement="Users frequently request an offline mode",
              sources=[Source(passage="Reviews show users frequently request an offline mode.")])
    out = verify_claim_formal(c, nli=StubNLI(), formal_verifier=StubFormalVerifier())
    assert out.verdict == Verdict.SUPPORTED                      # from NLI, not formal
    assert not any(sc.kind.startswith("formal:") for sc in out.structured_checks)


def test_formal_abstain_records_check_then_falls_back():
    # Math-routed via the heuristic (nli=None); the stub engine abstains, so it
    # records the formal attempt and falls back to entailment — which, with no
    # sources, is UNSUPPORTED (never fabricated support).
    c = Claim(statement="The integer 7 is prime")
    out = verify_claim_formal(c, nli=None, formal_verifier=StubFormalVerifier())
    assert any(sc.kind == "formal:stub" for sc in out.structured_checks)  # formal ran
    assert out.verdict == Verdict.UNSUPPORTED                              # abstained, nothing to ground
