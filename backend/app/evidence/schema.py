"""The claim primitive (OR-55).

A finding is a discrete, atomic, *verifiable* object — never prose — following
FActScore / SAFE / VeriScore. VeriScore's refinement matters here: only claims
that could in principle be checked against a source are extracted; opinion and
judgment are dropped, because a validation report mixes both and only the
former is gradeable.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class ClaimType(str, Enum):
    # The idea-validation dimensions (docs/evidence-contract.md open question).
    DEMAND = "demand"
    COMPETITION = "competition"
    PRICING = "pricing"
    FEASIBILITY = "feasibility"
    REGULATORY = "regulatory"
    OTHER = "other"


class Stance(str, Enum):
    SUPPORT = "support"   # the claim argues *for* the thesis under test
    REFUTE = "refute"     # the claim argues *against* it


class Verdict(str, Enum):
    SUPPORTED = "supported"       # a source entails it
    REFUTED = "refuted"           # a source contradicts it
    UNSUPPORTED = "unsupported"   # no source entails it (incl. fabricated citations)
    UNCERTAIN = "uncertain"       # below the confidence floor — abstain / escalate


class EntailmentLabel(str, Enum):
    ENTAIL = "entail"
    NEUTRAL = "neutral"
    CONTRADICT = "contradict"


class SourceTier(str, Enum):
    PRIMARY = "primary"       # the thing itself (a user complaint, a filing)
    SECONDARY = "secondary"   # something reporting on it (a blog, a summary)


class Source(BaseModel):
    url: str = ""
    passage: str                       # the exact text the claim is checked against
    tier: SourceTier = SourceTier.SECONDARY
    published_at: str | None = None
    retrieved_at: str | None = None


class Entailment(BaseModel):
    """Layer-2 result for one (claim, source) pair."""
    label: EntailmentLabel
    score: float                       # probability of `label`, 0..1
    source_index: int


class StructuredCheck(BaseModel):
    """Layer-1 result (numbers/dates). Populated by a later ticket."""
    kind: str
    passed: bool
    detail: str = ""


class AtomicClaim(BaseModel):
    """One atomic sub-claim of a statement (VeriScore-style decomposition).

    A statement like "scRNA-seq is valuable and has revolutionised biology" is an
    abstractive mix of checkable fact and opinion. Checking it whole makes a strict
    entailment model return *neutral* (low recall). Decomposing it, keeping only the
    `verifiable` atoms, and checking each against the source recovers recall without
    trusting a judge — the verdict still comes from mechanical NLI per atom.
    """
    text: str
    verifiable: bool = True            # False = opinion/judgment; not graded
    verdict: Verdict = Verdict.UNSUPPORTED
    confidence: float = 0.0


class Claim(BaseModel):
    statement: str
    type: ClaimType = ClaimType.OTHER
    stance: Stance = Stance.SUPPORT
    sources: list[Source] = Field(default_factory=list)

    # Filled by verification.
    atoms: list[AtomicClaim] = Field(default_factory=list)
    entailments: list[Entailment] = Field(default_factory=list)
    structured_checks: list[StructuredCheck] = Field(default_factory=list)
    confidence: float = 0.0
    verdict: Verdict = Verdict.UNSUPPORTED

    def best_entailment(self) -> Entailment | None:
        """The strongest ENTAIL, else the strongest of whatever there is."""
        if not self.entailments:
            return None
        entails = [e for e in self.entailments if e.label == EntailmentLabel.ENTAIL]
        pool = entails or self.entailments
        return max(pool, key=lambda e: e.score)
