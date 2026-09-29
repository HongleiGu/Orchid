"""Turn NLI results into a claim verdict + confidence (OR-56).

Aggregation only — the layer wiring (Layer 1 structured checks, Layer 3
invariants, Layer 4 judge) and calibrated thresholds are later tickets. The
confidence here is a first, uncalibrated estimate; OR-60 replaces the fixed
floor with thresholds fitted against the outcome store.
"""
from __future__ import annotations

from app.evidence.nli import NLIVerifier
from app.evidence.schema import Claim, Entailment, EntailmentLabel, Stance, Verdict

# Minimum probability to act on an entail/contradict signal. Below the floor the
# claim is UNCERTAIN — abstain / escalate rather than assert (selective
# prediction). Placeholder value; OR-60 calibrates it.
CONFIDENCE_FLOOR = 0.6


def verify_claim(claim: Claim, nli: NLIVerifier) -> Claim:
    """Check every source against the claim and set entailments, verdict, confidence.

    A claim with no sources — or whose sources do not entail it, as with a
    fabricated citation — is UNSUPPORTED, never supported by default.
    """
    claim.entailments = [
        Entailment(label=(res := nli.entail(src.passage, claim.statement))[0], score=res[1], source_index=i)
        for i, src in enumerate(claim.sources)
    ]

    entails = [e for e in claim.entailments if e.label == EntailmentLabel.ENTAIL]
    contradicts = [e for e in claim.entailments if e.label == EntailmentLabel.CONTRADICT]
    strong_entail = [e for e in entails if e.score >= CONFIDENCE_FLOOR]
    strong_contra = [e for e in contradicts if e.score >= CONFIDENCE_FLOOR]

    if not claim.sources:
        claim.verdict, claim.confidence = Verdict.UNSUPPORTED, 0.0
        return claim

    # A found entailment establishes the claim; a found contradiction refutes it.
    # When both exist (sources disagree), the stronger signal wins.
    best_entail = max(strong_entail, key=lambda e: e.score, default=None)
    best_contra = max(strong_contra, key=lambda e: e.score, default=None)

    if best_entail and (not best_contra or best_entail.score >= best_contra.score):
        # For a refute-stance claim, "entailed" means the refutation holds.
        claim.verdict = Verdict.REFUTED if claim.stance == Stance.REFUTE else Verdict.SUPPORTED
        claim.confidence = best_entail.score
    elif best_contra:
        claim.verdict = Verdict.SUPPORTED if claim.stance == Stance.REFUTE else Verdict.REFUTED
        claim.confidence = best_contra.score
    else:
        # Something was retrieved but nothing entailed or contradicted with
        # enough confidence — the fabricated-citation case, and genuine "no
        # evidence" alike.
        top = claim.best_entailment()
        claim.verdict = Verdict.UNSUPPORTED
        claim.confidence = 1.0 - top.score if top else 0.0

    return claim


def verify_claims(claims: list[Claim], nli: NLIVerifier) -> list[Claim]:
    return [verify_claim(c, nli) for c in claims]
