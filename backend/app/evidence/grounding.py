"""Pure grounding computation — shared by the DAG `grounded` check and the NLI
sidecar service, with no dependency on the DAG engine or app.core.

`ground_claims` is the body of the Layer-2 grounding gate: split nothing here
(callers pass claims + evidence chunks), decompose each claim into atoms when a
decomposer is given, and ground each atom against the full evidence set with
early-exit. Returns a plain dict so it serialises straight over HTTP.
"""
from __future__ import annotations

import re
from typing import Any

_SENT_SPLIT = re.compile(r"(?<=[.!?。！？])\s+")


def split_claims(text: str, max_claims: int = 40) -> list[str]:
    sents = [s.strip() for s in _SENT_SPLIT.split(text or "") if len(s.strip()) >= 25]
    return sents[:max_claims]


def chunk_sources(texts: list[str], max_chunks: int = 40, group: int = 3) -> list[str]:
    """Chunk evidence texts into ~`group`-sentence windows so each NLI premise is
    model-sized."""
    chunks: list[str] = []
    for t in texts:
        parts = _SENT_SPLIT.split(t or "")
        for i in range(0, len(parts), group):
            chunk = " ".join(p.strip() for p in parts[i:i + group]).strip()
            if chunk:
                chunks.append(chunk)
    return chunks[:max_chunks]


def ground_claims(verifier: Any, claims: list[str], sources: list[str], min_grounded: float = 0.8,
                  decomposer: Any = None, support_fraction: float = 0.5) -> dict:
    """Ground each claim against the evidence chunks. With a decomposer, each claim
    is split into atoms and grounded atom-by-atom against the full evidence set
    (early-exit); otherwise the whole sentence is matched against the chunks."""
    from app.evidence.schema import Claim, EntailmentLabel, Source, Verdict
    from app.evidence.verify import CONFIDENCE_FLOOR, _best_entailment_for, verify_claim_decomposed

    srcs = [Source(passage=s) for s in sources]
    holder = Claim(statement="", sources=srcs)
    ungrounded: list[str] = []
    for stmt in claims:
        if decomposer is not None:
            c = verify_claim_decomposed(Claim(statement=stmt, sources=srcs), verifier,
                                        decomposer, support_fraction=support_fraction)
            grounded = c.verdict == Verdict.SUPPORTED
        else:
            deciding, _ = _best_entailment_for(verifier, holder, stmt, CONFIDENCE_FLOOR)
            grounded = deciding.label == EntailmentLabel.ENTAIL and deciding.score >= CONFIDENCE_FLOOR
        if not grounded:
            ungrounded.append(stmt)
    n = len(claims)
    n_grounded = n - len(ungrounded)
    frac = n_grounded / n if n else 1.0
    reason = (f"{n_grounded}/{n} claims grounded in {len(sources)} evidence chunks "
              f"= {frac:.0%} (threshold {min_grounded:.0%}).")
    if ungrounded:
        reason += " Ungrounded claims: " + " | ".join(u[:90] for u in ungrounded[:5])
    return {"ok": frac >= min_grounded, "reason": reason, "fraction": frac, "ungrounded": ungrounded}
