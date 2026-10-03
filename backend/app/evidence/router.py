"""Verifier router — route each claim to the strongest verifier it admits, and
have the claim carry the resulting artifact (research; see docs/verifier-router.md).

Lattice of verification strength:  proof > execution > entailment > argument > none.
This slice wires three routes: formal (Z3/Lean, imported lazily — optional),
argumentative (the Toulmin warrant + attack verifier), and atomic (NLI entailment).
Classification is a cheap heuristic here; a zero-shot NLI / small-LLM typer is the
drop-in upgrade.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import IntEnum

from app.evidence.nli import NLIVerifier
from app.evidence.schema import Verdict


class ClaimKind(str):
    FORMAL = "formal"
    ARGUMENTATIVE = "argumentative"
    ATOMIC = "atomic"
    OPINION = "opinion"


class Strength(IntEnum):
    NONE = 0
    ARGUMENT = 1
    ENTAILMENT = 2
    EXECUTION = 3
    PROOF = 4


@dataclass
class ProofCarryingVerdict:
    kind: str
    verdict: Verdict
    strength: Strength
    artifact: dict = field(default_factory=dict)
    detail: str = ""


_FORMAL = re.compile(r"(\d+\s*[+\-*/=<>]\s*\d+|[=<>≤≥≠]|\bprime\b|\beven\b|\bodd\b|\binteger\b"
                     r"|\bdivisible\b|\bfor all\b|\bthere exists\b|∀|∃|√|≡|\bmod(ulo)?\b)", re.I)
_REASON = re.compile(r"\b(because|since|therefore|thus|hence|so that|implies|which means|leads to|"
                     r"as a result|consequently)\b", re.I)
_OPINION = re.compile(r"\b(i think|i believe|in my opinion|arguably|probably the best|should|"
                      r"beautiful|wonderful|terrible)\b", re.I)


def classify_claim(statement: str) -> str:
    s = statement or ""
    if _FORMAL.search(s):
        return ClaimKind.FORMAL
    if _OPINION.search(s):
        return ClaimKind.OPINION
    if _REASON.search(s):
        return ClaimKind.ARGUMENTATIVE
    return ClaimKind.ATOMIC


def verify_routed(statement: str, evidence: list[str], nli: NLIVerifier,
                  miner=None, formal_verifier=None, floor: float = 0.6) -> ProofCarryingVerdict:
    kind = classify_claim(statement)

    if kind == ClaimKind.FORMAL and formal_verifier is not None:
        res = formal_verifier.verify(statement)
        return ProofCarryingVerdict(kind, res.verdict, Strength.PROOF,
                                    {"engine": res.engine, "formalization": res.formalization},
                                    res.detail)

    if kind == ClaimKind.OPINION:
        return ProofCarryingVerdict(kind, Verdict.UNCERTAIN, Strength.NONE, {}, "opinion — not graded")

    if kind == ClaimKind.ARGUMENTATIVE and miner is not None:
        from app.evidence.argument import verify_argument
        av = verify_argument(miner.mine(statement), evidence, nli, floor=floor)
        return ProofCarryingVerdict(kind, av.verdict, Strength.ARGUMENT, av.graph(),
                                    f"grounds {sum(av.grounds_grounded)}/{len(av.grounds_grounded)}, "
                                    f"warrant={'ok' if av.warrant_valid else 'invalid'}, "
                                    f"attacks={len(av.attacks)}")

    # atomic (or argumentative with no miner): whole-claim NLI entailment
    from app.evidence.grounding import ground_claims
    r = ground_claims(nli, [statement], evidence, min_grounded=0.5)
    d = r["details"][0]
    verdict = Verdict.SUPPORTED if d["grounded"] else Verdict.UNSUPPORTED
    return ProofCarryingVerdict(ClaimKind.ATOMIC, verdict, Strength.ENTAILMENT,
                                {"confidence": d["confidence"]}, r["reason"])
