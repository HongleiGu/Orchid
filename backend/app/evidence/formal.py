"""Formal-verification layer for mathematical claims (research).

Beyond Layer 2: where NLI gives *entailment* grounding, a math claim can be given
*proof-level* grounding. The pipeline is:

    claim --(NLI router: is this math?)--> formal verifier --> proved / refuted / unknown

Two engines sit behind one `FormalVerifier` seam:
  * **Z3 (now)** — autoformalize the claim to SMT-LIB2 and check *validity* by
    refuting its negation (unsat ⇒ the claim is a theorem). Pure pip, decidable
    fragments (arithmetic, reals/ints, bitvectors), deployable today. The VeriFin
    pattern already named in the design note.
  * **Lean (future)** — the Numina-Lean-agent architecture (a general LLM driving
    the Lean proof assistant over MCP). Heavyweight (Lean + Mathlib, GPU provers);
    left as a documented stub here.

Honest boundary: Z3 verifies the *formalised* statement; whether the NL→SMT
translation is *faithful* is a separate problem (autoformalization robustness).
We record the formalisation so it is auditable, and treat an unparseable or
non-decidable result as UNCERTAIN (abstain), never as support.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable, Protocol

from app.evidence.nli import NLIVerifier
from app.evidence.schema import EntailmentLabel, Verdict

MATH_HYPOTHESIS = "This statement is a precise mathematical claim that could be proved or disproved."
# Cheap signals so the router has a model-free fallback.
_MATH_HINTS = re.compile(
    r"(\d+\s*[+\-*/=<>]\s*\d+|[=<>≤≥≠]|\bprime\b|\beven\b|\bodd\b|\binteger\b|\bdivisible\b"
    r"|\bfor all\b|\bthere exists\b|\bsum of\b|\bsquare\b|\bmodulo\b|∀|∃|√|∑|≡)",
    re.I,
)


@dataclass
class FormalResult:
    verdict: Verdict
    engine: str                     # "z3" | "lean" | "stub"
    detail: str = ""
    formalization: str = ""         # the SMT/Lean the claim was translated to (auditable)


def is_math_claim(statement: str, nli: NLIVerifier | None = None, threshold: float = 0.6) -> tuple[bool, float]:
    """Route: is this a formally-checkable mathematical claim? Uses the NLI model
    zero-shot (entailment of a 'this is a math claim' hypothesis); falls back to a
    keyword heuristic when no NLI is available."""
    if nli is not None:
        label, score = nli.entail(statement, MATH_HYPOTHESIS)
        if label == EntailmentLabel.ENTAIL:
            return score >= threshold, score
        return False, 1.0 - score
    hit = bool(_MATH_HINTS.search(statement or ""))
    return hit, 1.0 if hit else 0.0


class FormalVerifier(Protocol):
    def verify(self, statement: str) -> FormalResult: ...


# ── Z3 / SMT engine ──────────────────────────────────────────────────────────

_SMT_PROMPT = (
    "Translate the mathematical CLAIM into SMT-LIB2 for Z3. Quantify ALL variables"
    " so the formula is closed. Reply with JSON only:"
    ' {{"declarations": "<sort/function decls, may be empty>", "claim": "<a single'
    ' boolean SMT-LIB2 term that is TRUE iff the claim holds>"}}.'
    " Use the theory of integers/reals as appropriate. If the claim cannot be"
    ' expressed in decidable SMT, reply {{"declarations": "", "claim": ""}}.\n\n'
    "CLAIM: {statement}\n"
)


class Z3Verifier:
    """Autoformalize to SMT-LIB2, then check validity by refuting the negation."""

    def __init__(self, model: str, formalize_fn: Callable[[str], str] | None = None) -> None:
        self.model = model
        self._formalize = formalize_fn or self._litellm_formalize

    def _litellm_formalize(self, statement: str) -> str:
        import litellm

        resp = litellm.completion(
            model=self.model,
            messages=[{"role": "system", "content": "You formalise math into SMT-LIB2. Reply JSON only."},
                      {"role": "user", "content": _SMT_PROMPT.format(statement=statement)}],
            temperature=0.0,
        )
        return resp["choices"][0]["message"]["content"]

    def verify(self, statement: str) -> FormalResult:
        decls, claim = _parse_smt(self._formalize(statement))
        if not claim:
            return FormalResult(Verdict.UNCERTAIN, "z3", "claim not expressible in decidable SMT")
        script = f"{decls}\n(assert (not {claim}))\n"
        try:
            import z3

            solver = z3.Solver()
            solver.add(z3.parse_smt2_string(script))
            res = solver.check()
        except Exception as exc:  # malformed SMT from the formaliser
            return FormalResult(Verdict.UNCERTAIN, "z3", f"SMT error: {exc}", formalization=claim)
        if res == z3.unsat:
            return FormalResult(Verdict.SUPPORTED, "z3", "negation unsatisfiable → claim is valid", claim)
        if res == z3.sat:
            model = solver.model()
            return FormalResult(Verdict.REFUTED, "z3", f"counterexample: {model}", claim)
        return FormalResult(Verdict.UNCERTAIN, "z3", "z3 returned unknown", claim)


def _parse_smt(raw: str) -> tuple[str, str]:
    m = re.search(r"\{.*\}", raw or "", re.S)
    if not m:
        return "", ""
    try:
        d = json.loads(m.group(0))
        return str(d.get("declarations", "") or ""), str(d.get("claim", "") or "").strip()
    except (ValueError, TypeError):
        return "", ""


# ── Lean engine (future; Numina-Lean-agent over MCP) ─────────────────────────

class LeanVerifier:
    """Placeholder for the Lean path: a general LLM driving the Lean proof
    assistant over MCP (the Numina-Lean-agent architecture), for claims beyond
    decidable SMT. Not wired here — returns UNCERTAIN so it never fabricates a
    proof. The seam exists so the router can prefer Z3 and fall through to Lean."""

    def verify(self, statement: str) -> FormalResult:
        return FormalResult(Verdict.UNCERTAIN, "lean", "lean verifier not configured")


class StubFormalVerifier:
    """Deterministic engine for tests: proves a tiny set of ground truths, refutes
    an obvious falsehood, else abstains. No LLM, no solver."""

    def verify(self, statement: str) -> FormalResult:
        s = statement.lower().replace(" ", "")
        if "2+2=4" in s or "sumoftwoevennumbersiseven" in s:
            return FormalResult(Verdict.SUPPORTED, "stub", "known true")
        if "2+2=5" in s:
            return FormalResult(Verdict.REFUTED, "stub", "known false")
        return FormalResult(Verdict.UNCERTAIN, "stub", "not in stub ground truth")
