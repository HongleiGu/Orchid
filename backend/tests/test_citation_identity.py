"""Citation-identity check (OR-58): flags named sources absent from the evidence."""
from __future__ import annotations

from app.evidence.citation_identity import extract_named_sources, unsupported_citations

# Mirrors the real confabulation observed in the pipeline brief: the sources did
# mention FairJudge and the RAND Corporation, but not JudgeBiasBench / the names.
BRIEF = (
    "Frontier models exceeded 50% error rates, according to Hongli Zhou and "
    "colleagues' JudgeBiasBench. Three limitations were identified by Bo Yang and "
    "colleagues in their FairJudge study. No judge evaluated by the RAND Corporation "
    "was uniformly reliable."
)
SOURCES = [
    "FairJudge training pipeline with three stages — SFT, DPO, GRPO.",
    "Morgan Sandler and colleagues at the RAND Corporation released a study where no "
    "judge was uniformly reliable across benchmarks.",
    "Lianmin Zheng and colleagues measured 80% agreement across 3000 expert votes.",
]


def test_flags_fabricated_names_but_clears_real_ones():
    flagged = set(unsupported_citations(BRIEF, SOURCES))
    assert "JudgeBiasBench" in flagged
    assert any("Hongli Zhou" in f or f == "Hongli Zhou" for f in flagged)
    assert any("Bo Yang" in f for f in flagged)
    # Present in the sources -> must NOT be flagged.
    assert "FairJudge" not in flagged
    assert "RAND Corporation" not in flagged


def test_extract_ignores_sentence_openers():
    names = extract_named_sources("Studies show that the RAND Corporation found bias.")
    assert "RAND Corporation" in names
    assert "Studies" not in names


def test_no_flags_when_all_named_sources_present():
    assert unsupported_citations("The RAND Corporation study found bias.", SOURCES) == []
