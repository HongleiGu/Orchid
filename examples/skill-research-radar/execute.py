"""
Research Radar — broad direction spotting across multiple academic sources.

Sources:
  1. arXiv API (recent papers by field)
  2. Semantic Scholar (citation velocity — what's gaining traction)
  3. HuggingFace Daily Papers (community curation)
  4. HuggingFace Trending Models (practical adoption signals)
  5. Papers With Code (SOTA benchmark changes)
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 12

BREADTH_EXPANSIONS = {
    "focused": [],
    "broad": [
        "{field} survey",
        "{field} benchmark",
    ],
    "exploratory": [
        "{field} survey",
        "{field} benchmark",
        "{field} alternative approach",
        "{field} interdisciplinary",
    ],
}


async def execute(
    field: str,
    time_window: str = "month",
    breadth: str = "broad",
    max_results_per_source: int = 5,
) -> str:
    n = max_results_per_source

    # Build query variants based on breadth
    queries = [field]
    for template in BREADTH_EXPANSIONS.get(breadth, []):
        queries.append(template.format(field=field))

    # Fetch from all sources concurrently-ish
    all_papers: list[dict] = []
    source_counts: dict[str, int] = {}

    # 1. arXiv — one search per query variant
    for q in queries[:3]:
        papers = await _search_arxiv(q, n)
        all_papers.extend(papers)
    source_counts["arXiv"] = len([p for p in all_papers if p["source"] == "arXiv"])

    # 2. Semantic Scholar — citation velocity (influential recent papers)
    ss_papers = await _search_semantic_scholar(field, n, time_window)
    all_papers.extend(ss_papers)
    source_counts["Semantic Scholar"] = len(ss_papers)

    # 3. HuggingFace Daily Papers
    hf_papers = await _fetch_huggingface_papers(n)
    all_papers.extend(hf_papers)
    source_counts["HuggingFace Papers"] = len(hf_papers)

    # 4. HuggingFace Trending Models
    hf_models = await _fetch_huggingface_models(field, n)
    all_papers.extend(hf_models)
    source_counts["HuggingFace Models"] = len(hf_models)

    # 5. Papers With Code — SOTA
    pwc = await _fetch_papers_with_code(field, n)
    all_papers.extend(pwc)
    source_counts["Papers With Code"] = len(pwc)

    # Deduplicate by title similarity
    unique = _deduplicate(all_papers)

    # Build report
    return _build_report(field, time_window, breadth, unique, source_counts)


# ── Source fetchers ───────────────────────────────────────────────────────────

async def _search_arxiv(query: str, limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "http://export.arxiv.org/api/query",
                params={
                    "search_query": f"all:{query}",
                    "start": 0,
                    "max_results": limit,
                    "sortBy": "submittedDate",
                    "sortOrder": "descending",
                },
            )
            resp.raise_for_status()

        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        papers = []
        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
            abstract = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
            authors = ", ".join(
                a.findtext("atom:name", "", ns) for a in entry.findall("atom:author", ns)
            )[:200]
            link = ""
            for l in entry.findall("atom:link", ns):
                if l.get("type") == "text/html":
                    link = l.get("href", "")
                    break
            if not link:
                id_el = entry.find("atom:id", ns)
                link = id_el.text if id_el is not None else ""

            papers.append({
                "title": title,
                "authors": authors,
                "abstract": abstract[:300],
                "url": link,
                "source": "arXiv",
                "signal": "recent",
            })
        return papers
    except Exception as exc:
        logger.warning("arXiv search failed for %r: %s", query, exc)
        return []


async def _search_semantic_scholar(query: str, limit: int, time_window: str) -> list[dict]:
    """Find high citation-velocity papers (trending academically)."""
    year_cutoff = {
        "week": datetime.now().year,
        "month": datetime.now().year,
        "quarter": datetime.now().year - 1,
    }.get(time_window, datetime.now().year)

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": query,
                    "limit": limit * 2,  # fetch extra, then sort by citations
                    "fields": "title,abstract,url,authors,year,citationCount,influentialCitationCount",
                    "year": f"{year_cutoff}-",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        papers_raw = data.get("data", [])
        # Sort by citation velocity (citations / age)
        papers_raw.sort(
            key=lambda p: (p.get("influentialCitationCount", 0), p.get("citationCount", 0)),
            reverse=True,
        )

        papers = []
        for p in papers_raw[:limit]:
            authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3])
            citations = p.get("citationCount", 0)
            influential = p.get("influentialCitationCount", 0)
            abstract = (p.get("abstract") or "")[:300]
            papers.append({
                "title": p.get("title", ""),
                "authors": authors,
                "abstract": f"[{citations} citations, {influential} influential] {abstract}",
                "url": p.get("url", ""),
                "source": "Semantic Scholar",
                "signal": f"{citations} citations",
            })
        return papers
    except Exception as exc:
        logger.warning("Semantic Scholar failed: %s", exc)
        return []


async def _fetch_huggingface_papers(limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://huggingface.co/api/daily_papers")
            resp.raise_for_status()
            data = resp.json()

        papers = []
        for item in data[:limit]:
            paper = item.get("paper", {})
            authors = ", ".join(a.get("name", "") for a in (paper.get("authors") or [])[:3])
            paper_id = paper.get("id", "")
            papers.append({
                "title": paper.get("title", ""),
                "authors": authors,
                "abstract": (paper.get("summary") or "")[:300],
                "url": f"https://huggingface.co/papers/{paper_id}" if paper_id else "",
                "source": "HuggingFace Papers",
                "signal": "community trending",
            })
        return papers
    except Exception as exc:
        logger.warning("HuggingFace papers failed: %s", exc)
        return []


async def _fetch_huggingface_models(field: str, limit: int) -> list[dict]:
    """Trending models — signals practical adoption."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://huggingface.co/api/models",
                params={"search": field, "sort": "trending", "limit": limit},
            )
            resp.raise_for_status()
            data = resp.json()

        items = []
        for m in data[:limit]:
            model_id = m.get("modelId", "")
            items.append({
                "title": f"Model: {model_id}",
                "authors": m.get("author", ""),
                "abstract": f"Downloads: {m.get('downloads', 0):,} | Likes: {m.get('likes', 0)} | Pipeline: {m.get('pipeline_tag', 'unknown')}",
                "url": f"https://huggingface.co/{model_id}",
                "source": "HuggingFace Models",
                "signal": f"{m.get('downloads', 0):,} downloads",
            })
        return items
    except Exception as exc:
        logger.warning("HuggingFace models failed: %s", exc)
        return []


async def _fetch_papers_with_code(field: str, limit: int) -> list[dict]:
    """Papers With Code — SOTA benchmark papers."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://paperswithcode.com/api/v1/papers/",
                params={"q": field, "items_per_page": limit, "ordering": "-proceeding"},
            )
            resp.raise_for_status()
            data = resp.json()

        papers = []
        for p in data.get("results", [])[:limit]:
            papers.append({
                "title": p.get("title", ""),
                "authors": p.get("authors", [""])[:3] if isinstance(p.get("authors"), list) else "",
                "abstract": (p.get("abstract") or "")[:300],
                "url": p.get("url_abs", "") or p.get("paper_url", ""),
                "source": "Papers With Code",
                "signal": "SOTA benchmark",
            })
        return papers
    except Exception as exc:
        logger.warning("Papers With Code failed: %s", exc)
        return []


# ── Deduplication + Report ────────────────────────────────────────────────────

def _deduplicate(papers: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for p in papers:
        key = p["title"].lower().strip()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _build_report(
    field: str, time_window: str, breadth: str,
    papers: list[dict], source_counts: dict[str, int],
) -> str:
    lines = [
        f"# Research Radar: {field}",
        f"**Window**: {time_window} | **Breadth**: {breadth} | **Total unique items**: {len(papers)}",
        f"**Sources**: {', '.join(f'{k}: {v}' for k, v in source_counts.items())}",
        "",
    ]

    # Group by source
    by_source: dict[str, list[dict]] = {}
    for p in papers:
        by_source.setdefault(p["source"], []).append(p)

    for source, items in by_source.items():
        lines.append(f"## {source}")
        lines.append("")
        for p in items:
            title = p["title"]
            url = p.get("url", "")
            signal = p.get("signal", "")
            abstract = p.get("abstract", "")

            if url:
                lines.append(f"### [{title}]({url})")
            else:
                lines.append(f"### {title}")

            if p.get("authors"):
                lines.append(f"*{p['authors']}*")
            if signal:
                lines.append(f"**Signal**: {signal}")
            if abstract:
                lines.append(f"> {abstract}")
            lines.append("")

    return "\n".join(lines)
