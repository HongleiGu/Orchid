"""Turn NLI results into a claim verdict + confidence (OR-56).

Aggregation only — the layer wiring (Layer 1 structured checks, Layer 3
invariants, Layer 4 judge) and calibrated thresholds are later tickets. The
confidence here is a first, uncalibrated estimate; OR-60 replaces the fixed
floor with thresholds fitted against the outcome store.
"""
from __future__ import annotations

from app.evidence.nli import NLIVerifier
from app.evidence.schema import (
    AtomicClaim,
    Claim,
    Entailment,
    EntailmentLabel,
    Stance,
    Verdict,
)

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


def _best_entailment_for(nli: NLIVerifier, claim: Claim, hypothesis: str,
                         floor: float) -> tuple[Entailment, Entailment | None]:
    """Check one hypothesis against every source; return (deciding, strongest).

    Early-exits at the first strongly-entailing source, so testing an atom against
    many grounding passages stays cheap for genuine claims. `deciding` is that
    entailment, else the strongest contradiction, else the strongest signal seen.
    """
    best: Entailment | None = None
    best_contra: Entailment | None = None
    for i, src in enumerate(claim.sources):
        label, score = nli.entail(src.passage, hypothesis)
        e = Entailment(label=label, score=score, source_index=i)
        if best is None or score > best.score:
            best = e
        if label == EntailmentLabel.ENTAIL and score >= floor:
            return e, e
        if label == EntailmentLabel.CONTRADICT and score >= floor and (
            best_contra is None or score > best_contra.score
        ):
            best_contra = e
    return (best_contra or best), best  # type: ignore[return-value]


# How much of a claim must be grounded to call it supported. Strict "all atoms"
# (=1.0) tanks recall on abstractive, multi-source sentences; a majority is the
# practical middle. Tunable; OR-60 calibrates it against the outcome store.
SUPPORT_FRACTION = 0.5
# A contradiction only flips the verdict to REFUTED when it is strong AND actually
# dominates the supporting atoms — otherwise a single negation-shaped atom (which
# a 3-way MNLI model misreads) would wrongly refute a genuine claim.
REFUTE_FLOOR = 0.9


def verify_claim_decomposed(claim: Claim, nli: NLIVerifier, decomposer,
                            support_fraction: float = SUPPORT_FRACTION,
                            refute_floor: float = REFUTE_FLOOR) -> Claim:
    """Decompose the statement into atomic claims, verify each verifiable atom
    against the sources with NLI, and aggregate.

    Recall-oriented aggregation: a claim is supported when at least
    `support_fraction` of its *verifiable* atoms are entailed by some source
    (opinion atoms are not graded); it is refuted only when strong contradictions
    dominate the supporting atoms; otherwise unsupported. With no verifiable atoms
    (pure opinion) there is nothing to check — fall back to whole-statement
    verification.
    """
    if not claim.sources:
        claim.verdict, claim.confidence = Verdict.UNSUPPORTED, 0.0
        return claim

    claim.atoms = decomposer.decompose(claim.statement)
    verifiable = [a for a in claim.atoms if a.verifiable]
    if not verifiable:
        return verify_claim(claim, nli)

    decided: list[Entailment] = []
    atom_supported, atom_contradicted = [], []
    for atom in verifiable:
        e, best = _best_entailment_for(nli, claim, atom.text, CONFIDENCE_FLOOR)
        decided.append(e)
        if e.label == EntailmentLabel.ENTAIL and e.score >= CONFIDENCE_FLOOR:
            atom.verdict, atom.confidence = Verdict.SUPPORTED, e.score
            atom_supported.append(atom)
        elif e.label == EntailmentLabel.CONTRADICT and e.score >= CONFIDENCE_FLOOR:
            atom.verdict, atom.confidence = Verdict.REFUTED, e.score
            atom_contradicted.append(atom)
        else:
            atom.verdict = Verdict.UNSUPPORTED
            atom.confidence = 1.0 - best.score if best else 0.0
    claim.entailments = decided

    supported_is = Verdict.REFUTED if claim.stance == Stance.REFUTE else Verdict.SUPPORTED
    refuted_is = Verdict.SUPPORTED if claim.stance == Stance.REFUTE else Verdict.REFUTED

    n = len(verifiable)
    n_sup = len(atom_supported)
    strong_contra = [a for a in atom_contradicted if a.confidence >= refute_floor]
    frac_sup = n_sup / n

    if strong_contra and len(atom_contradicted) > n_sup:
        # Contradiction genuinely dominates — not just one misread atom.
        claim.verdict = refuted_is
        claim.confidence = max(a.confidence for a in atom_contradicted)
    elif frac_sup >= support_fraction:
        claim.verdict = supported_is
        claim.confidence = frac_sup
    else:
        claim.verdict = Verdict.UNSUPPORTED
        claim.confidence = 1.0 - frac_sup
    return claim


def verify_claims(claims: list[Claim], nli: NLIVerifier) -> list[Claim]:
    return [verify_claim(c, nli) for c in claims]
