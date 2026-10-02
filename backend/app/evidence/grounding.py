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

# Scrape boilerplate that pollutes retrieved "content": nav, bylines, site chrome.
# Grounding against these fragments is the garbage-in failure that sinks recall.
_BOILERPLATE = re.compile(
    r"(back to arxiv|arxiv logo|learn more|frequently asked questions|license:\s*cc\b"
    r"|cookie|subscribe|sign in|all rights reserved|read more|share this|related articles"
    r"|^\s*by\s+[A-Z][a-z]+(\s+[A-Z][a-z]+)?\s*$)",
    re.I,
)
_DATE_ONLY = re.compile(r"^\s*((january|february|march|april|may|june|july|august|september|october"
                        r"|november|december)\s+\d{1,2},?\s*\d{0,4}|\d{4}-\d{2}-\d{2})\s*$", re.I)


def clean_evidence(text: str) -> str:
    """Strip markdown/scrape boilerplate so grounding sees prose, not site chrome.
    Conservative: drops header marks, boilerplate and date/byline lines, then
    collapses whitespace — keeps anything that looks like a real sentence."""
    kept: list[str] = []
    for line in (text or "").splitlines():
        s = re.sub(r"^#+\s*", "", line).strip()      # markdown headers -> plain
        if not s or _BOILERPLATE.search(s) or _DATE_ONLY.match(s):
            continue
        # drop very short non-sentence fragments (nav items, list bullets)
        if len(s) < 25 and not re.search(r"[.!?。！？]", s):
            continue
        kept.append(s)
    return re.sub(r"\s+", " ", " ".join(kept)).strip()


def split_claims(text: str, max_claims: int = 40) -> list[str]:
    sents = [s.strip() for s in _SENT_SPLIT.split(text or "") if len(s.strip()) >= 25]
    return sents[:max_claims]


def chunk_sources(texts: list[str], max_chunks: int = 40, group: int = 3, clean: bool = True) -> list[str]:
    """Chunk evidence texts into ~`group`-sentence windows so each NLI premise is
    model-sized. Cleans scrape boilerplate first (disable with clean=False)."""
    chunks: list[str] = []
    for t in texts:
        parts = _SENT_SPLIT.split(clean_evidence(t) if clean else (t or ""))
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
    details: list[dict] = []   # per-claim {text, grounded, confidence} for calibration
    for stmt in claims:
        if decomposer is not None:
            c = verify_claim_decomposed(Claim(statement=stmt, sources=srcs), verifier,
                                        decomposer, support_fraction=support_fraction)
            grounded = c.verdict == Verdict.SUPPORTED
            confidence = c.confidence
        else:
            deciding, _ = _best_entailment_for(verifier, holder, stmt, CONFIDENCE_FLOOR)
            grounded = deciding.label == EntailmentLabel.ENTAIL and deciding.score >= CONFIDENCE_FLOOR
            confidence = deciding.score
        details.append({"text": stmt, "grounded": grounded, "confidence": round(confidence, 4)})
        if not grounded:
            ungrounded.append(stmt)
    n = len(claims)
    n_grounded = n - len(ungrounded)
    frac = n_grounded / n if n else 1.0
    reason = (f"{n_grounded}/{n} claims grounded in {len(sources)} evidence chunks "
              f"= {frac:.0%} (threshold {min_grounded:.0%}).")
    if ungrounded:
        reason += " Ungrounded claims: " + " | ".join(u[:90] for u in ungrounded[:5])
    return {"ok": frac >= min_grounded, "reason": reason, "fraction": frac,
            "ungrounded": ungrounded, "details": details}
