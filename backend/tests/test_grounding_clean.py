"""Evidence cleaning (OR-58): strip scrape boilerplate before grounding."""
from __future__ import annotations

from app.evidence.grounding import chunk_sources, clean_evidence

RAW = (
    "# LLM-as-a-Judge: Why Models Fail\n"
    "By Nilesh Barla\n"
    "April 8, 2026\n"
    "Studies published in 2025 show that no judge was uniformly reliable across benchmarks.\n"
    "arXiv logo Back to arXiv\n"
    "Frequently Asked Questions\n"
    "Frontier models exceeded 50% error rates on bias benchmarks.\n"
)


def test_clean_drops_boilerplate_keeps_prose():
    out = clean_evidence(RAW)
    assert "no judge was uniformly reliable" in out
    assert "exceeded 50% error rates" in out
    for junk in ("Back to arXiv", "arXiv logo", "Frequently Asked Questions", "By Nilesh Barla", "April 8"):
        assert junk not in out


def test_chunk_sources_cleans_by_default():
    chunks = " ".join(chunk_sources([RAW]))
    assert "no judge was uniformly reliable" in chunks
    assert "arXiv logo" not in chunks
    # with cleaning off, the boilerplate survives
    assert "arXiv logo" in " ".join(chunk_sources([RAW], clean=False))
