"""Citation-identity check — the layer NLI grounding does *not* cover.

Layer-2 NLI verifies that a claim's *content* is entailed by the evidence. It does
NOT verify that a source the claim *names* actually exists and is the one that
supports it. A writer can state a supported fact and attribute it to a plausible
but fabricated study ("…in the FairJudge study by Bo Yang", "…JudgeBiasBench"):
the content grounds, the citation identity is invented. This is the dominant
citation-hallucination failure the deep-research literature reports.

This is deliberately mechanical and cheap — NER-ish extraction + presence match
against the retrieved sources — not an LLM judge. A named entity the brief asserts
as a source but which appears nowhere in the retrieved passages is flagged.
"""
from __future__ import annotations

import re

# Acronym+TitleCase ("RAND Corporation"), CamelCase coinages ("FairJudge",
# "JudgeBiasBench"), and TitleCase runs / author names ("Bo Yang"). Ordered so the
# longest, most specific form wins at each position.
_CANDIDATE = re.compile(
    r"\b([A-Z]{2,}(?:\s+[A-Z][a-z]+)+"                 # RAND Corporation
    r"|[A-Z][a-z]+(?:[A-Z][a-zA-Z]*)+"                 # FairJudge / JudgeBiasBench
    r"|[A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b"          # Bo Yang / Titlecase run
)
# Words that start a sentence or are generic — not citation identities.
_STOP = {
    "The", "This", "These", "Those", "Their", "Studies", "Research", "Overall",
    "Additionally", "However", "While", "Frontier", "Non", "Three", "Both", "For",
    "Large", "Language", "Models", "Model", "Reliability", "Validity",
}


def extract_named_sources(text: str) -> list[str]:
    """Candidate source/entity names a brief asserts (studies, benchmarks, orgs,
    authors). Heuristic; favours recall so the presence check can clear them."""
    out: list[str] = []
    seen = set()
    for m in _CANDIDATE.finditer(text or ""):
        name = m.group(1).strip()
        first = name.split()[0]
        if first in _STOP or len(name) < 4:
            continue
        key = name.lower()
        if key not in seen:
            seen.add(key)
            out.append(name)
    return out


def unsupported_citations(brief: str, sources: list[str], min_token_overlap: float = 0.6) -> list[str]:
    """Named entities asserted in the brief that do NOT appear in any retrieved
    source — i.e. likely fabricated citation identities. A name clears if it (or
    most of its tokens) is present in the source text, case-insensitively."""
    hay = "\n".join(sources).lower()
    flagged: list[str] = []
    for name in extract_named_sources(brief):
        low = name.lower()
        if low in hay:
            continue
        toks = [t for t in re.findall(r"[a-z]+", low) if len(t) > 2]
        if toks and sum(t in hay for t in toks) / len(toks) >= min_token_overlap:
            continue  # most tokens present (minor phrasing diff) — accept
        flagged.append(name)
    return flagged
