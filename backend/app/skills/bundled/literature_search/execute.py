from __future__ import annotations

import asyncio
import os
import re
import xml.etree.ElementTree as ET
from typing import Any

import httpx

MAX_RESULTS = 25
TIMEOUT = 18


async def execute(
    query: str,
    queries: list[str] | None = None,
    arxiv_ids: list[str] | None = None,
    year_from: int = 2022,
    max_results: int = 12,
    include_semantic_scholar: bool = False,
) -> str:
    primary_query = (query or "").strip()
    extra_queries = [str(q).strip() for q in (queries or []) if str(q).strip()]
    search_queries = _unique([primary_query, *extra_queries])
    ids = _normalise_arxiv_ids(arxiv_ids or [])
    if not search_queries and not ids:
        return "Error: query must be non-empty."

    limit = max(1, min(int(max_results or 12), MAX_RESULTS))
    year = int(year_from or 2022)
    notes: list[str] = []
    coverage: dict[str, int] = {}

    async with httpx.AsyncClient(
        timeout=TIMEOUT,
        headers={"User-Agent": "Orchid literature_search/0.2"},
    ) as client:
        tasks = []
        labels = []
        for q in search_queries:
            tasks.append(_search_arxiv(client, q, year, limit))
            labels.append(f"arXiv:{q}")
            tasks.append(_search_openalex(client, q, year, limit))
            labels.append(f"OpenAlex:{q}")
        if ids:
            tasks.append(_fetch_arxiv_ids(client, ids, year))
            labels.append("arXiv:id_list")

        if include_semantic_scholar and os.environ.get("SEMANTIC_SCHOLAR_API_KEY"):
            for q in search_queries:
                tasks.append(_search_semantic_scholar(client, q, year, limit))
                labels.append(f"Semantic Scholar:{q}")
        elif include_semantic_scholar:
            notes.append("Skipped Semantic Scholar: SEMANTIC_SCHOLAR_API_KEY is not configured.")
        else:
            notes.append("Skipped Semantic Scholar by default to avoid unauthenticated 429 rate limits.")

        groups = await asyncio.gather(*tasks, return_exceptions=True)

    papers: list[dict[str, Any]] = []
    for label, group in zip(labels, groups):
        if isinstance(group, Exception):
            notes.append(f"Source error for {label}: {type(group).__name__}: {group}")
            coverage[label] = 0
            continue
        coverage[label] = len(group)
        papers.extend(group)

    deduped = _dedupe(papers)
    ranked = _rank(deduped)[:limit]
    return _format_report(search_queries, ids, year, ranked, notes, coverage)


async def _search_arxiv(
    client: httpx.AsyncClient,
    query: str,
    year_from: int,
    limit: int,
) -> list[dict[str, Any]]:
    resp = await client.get(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": _arxiv_query(query),
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
    )
    resp.raise_for_status()
    return _parse_arxiv_feed(resp.text, year_from, source="arXiv", signal="recent preprint")


async def _fetch_arxiv_ids(
    client: httpx.AsyncClient,
    ids: list[str],
    year_from: int,
) -> list[dict[str, Any]]:
    resp = await client.get(
        "https://export.arxiv.org/api/query",
        params={"id_list": ",".join(ids), "start": 0, "max_results": len(ids)},
    )
    resp.raise_for_status()
    papers = _parse_arxiv_feed(resp.text, year_from, source="arXiv direct", signal="canonical ID match")
    for paper in papers:
        paper["score"] = int(paper.get("score") or 0) + 2
    return papers


def _parse_arxiv_feed(text: str, year_from: int, source: str, signal: str) -> list[dict[str, Any]]:
    root = ET.fromstring(text)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    papers: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        published = entry.findtext("atom:published", "", ns)
        year = int(published[:4]) if published[:4].isdigit() else None
        if year is not None and year < year_from:
            continue
        title = _clean(entry.findtext("atom:title", "", ns))
        abstract = _clean(entry.findtext("atom:summary", "", ns))
        authors = ", ".join(
            _clean(a.findtext("atom:name", "", ns))
            for a in entry.findall("atom:author", ns)[:4]
        )
        url = entry.findtext("atom:id", "", ns)
        papers.append({
            "source": source,
            "title": title,
            "year": year or "",
            "venue": "arXiv",
            "authors": authors,
            "url": url,
            "abstract": abstract,
            "signal": signal,
            "score": _score(source, year or 0, 0, title, abstract),
        })
    return papers


async def _search_openalex(
    client: httpx.AsyncClient,
    query: str,
    year_from: int,
    limit: int,
) -> list[dict[str, Any]]:
    resp = await client.get(
        "https://api.openalex.org/works",
        params={
            "search": query,
            "filter": f"from_publication_date:{year_from}-01-01",
            "per-page": limit,
            "sort": "relevance_score:desc",
            "select": "id,display_name,publication_year,primary_location,authorships,cited_by_count,abstract_inverted_index",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    papers: list[dict[str, Any]] = []
    for item in data.get("results", []):
        location = item.get("primary_location") or {}
        source = location.get("source") or {}
        landing = location.get("landing_page_url") or location.get("pdf_url") or item.get("id", "")
        title = item.get("display_name", "")
        abstract = _openalex_abstract(item.get("abstract_inverted_index"))
        citations = item.get("cited_by_count", 0)
        year = item.get("publication_year") or ""
        authors = ", ".join(
            ((a.get("author") or {}).get("display_name") or "")
            for a in (item.get("authorships") or [])[:4]
        )
        papers.append({
            "source": "OpenAlex",
            "title": title,
            "year": year,
            "venue": source.get("display_name") or "OpenAlex",
            "authors": authors,
            "url": landing,
            "abstract": abstract,
            "signal": f"{citations} citations",
            "score": _score("OpenAlex", int(year or 0), int(citations or 0), title, abstract),
        })
    return papers


async def _search_semantic_scholar(
    client: httpx.AsyncClient,
    query: str,
    year_from: int,
    limit: int,
) -> list[dict[str, Any]]:
    api_key = os.environ["SEMANTIC_SCHOLAR_API_KEY"]
    resp = await client.get(
        "https://api.semanticscholar.org/graph/v1/paper/search",
        params={
            "query": query,
            "limit": limit,
            "fields": "title,year,venue,url,abstract,authors,citationCount",
            "year": f"{year_from}-",
        },
        headers={"x-api-key": api_key},
    )
    if resp.status_code == 429:
        return [{
            "source": "Semantic Scholar",
            "title": "Semantic Scholar skipped due to 429 rate limit",
            "year": "",
            "venue": "",
            "authors": "",
            "url": "https://www.semanticscholar.org/product/api",
            "abstract": "The API returned Too Many Requests. Use arXiv/OpenAlex results or configure a higher-limit key.",
            "signal": "429",
            "score": -10,
        }]
    resp.raise_for_status()
    data = resp.json()
    papers: list[dict[str, Any]] = []
    for item in data.get("data", []):
        title = item.get("title", "")
        abstract = item.get("abstract") or ""
        citations = item.get("citationCount", 0)
        year = item.get("year") or ""
        authors = ", ".join((a.get("name") or "") for a in (item.get("authors") or [])[:4])
        papers.append({
            "source": "Semantic Scholar",
            "title": title,
            "year": year,
            "venue": item.get("venue") or "Semantic Scholar",
            "authors": authors,
            "url": item.get("url", ""),
            "abstract": abstract,
            "signal": f"{citations} citations",
            "score": _score("Semantic Scholar", int(year or 0), int(citations or 0), title, abstract),
        })
    return papers


def _openalex_abstract(index: dict[str, list[int]] | None) -> str:
    if not index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, locs in index.items():
        for loc in locs:
            positions.append((loc, word))
    return " ".join(word for _, word in sorted(positions))[:1200]


def _dedupe(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for paper in papers:
        title = _clean(str(paper.get("title", "")))
        key = re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()
        if not key or key in seen:
            continue
        seen.add(key)
        paper["title"] = title
        out.append(paper)
    return out


def _rank(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        papers,
        key=lambda p: (
            int(p.get("score") or 0),
            int(p.get("year") or 0) if str(p.get("year") or "").isdigit() else 0,
        ),
        reverse=True,
    )


def _format_report(
    queries: list[str],
    arxiv_ids: list[str],
    year_from: int,
    papers: list[dict[str, Any]],
    notes: list[str],
    coverage: dict[str, int],
) -> str:
    title = queries[0] if queries else ", ".join(arxiv_ids)
    lines = [
        f"# Literature search: {title}",
        "",
        f"Filters: year_from={year_from}; sources=arXiv + OpenAlex by default; deduplicated_results={len(papers)}.",
        "",
        "## Query Plan",
    ]
    lines.extend(f"- Query: {q}" for q in queries)
    if arxiv_ids:
        lines.append(f"- Direct arXiv IDs: {', '.join(arxiv_ids)}")
    lines.append("")

    if coverage:
        lines.append("## Coverage Diagnostics")
        for label, count in coverage.items():
            lines.append(f"- {label}: {count} raw result(s)")
        lines.append("")

    if notes:
        lines.append("## Notes")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.extend([
        "## Screening Hints",
        "- Prefer peer-reviewed top-venue papers, benchmark/dataset papers with stable identifiers, and high-citation surveys.",
        "- Treat arXiv-only and very recent papers as weak until independently verified.",
        "- Do not report numerical claims unless they are present in the returned text or verified from the paper.",
        "",
        "## Results",
    ])
    if not papers:
        lines.append("No results found.")
        return "\n".join(lines)

    for i, paper in enumerate(papers, 1):
        abstract = _clean(str(paper.get("abstract", "")))[:450]
        lines.extend([
            f"{i}. **{paper.get('title', '')}** ({paper.get('year', 'n.d.')})",
            f"   - Source: {paper.get('source', '')}; venue: {paper.get('venue', '')}; signal: {paper.get('signal', '')}; relevance_score: {paper.get('score', 0)}",
            f"   - Authors: {paper.get('authors', '') or 'unknown'}",
            f"   - URL: {paper.get('url', '')}",
            f"   - Abstract: {abstract or 'not available'}",
        ])
    return "\n".join(lines)


def _clean(text: str) -> str:
    return " ".join((text or "").split())


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        key = item.lower()
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _normalise_arxiv_ids(ids: list[str]) -> list[str]:
    out: list[str] = []
    for raw in ids:
        match = re.search(r"(\d{4}\.\d{4,5})(?:v\d+)?", str(raw))
        if match:
            out.append(match.group(1))
    return _unique(out)


def _arxiv_query(query: str) -> str:
    terms = [t for t in re.split(r"\s+", query.strip()) if t]
    if not terms:
        return "all:LLM"
    # Field each term so broad natural-language queries do not become arXiv's
    # accidental OR searches. Cap terms to keep URLs small.
    return " AND ".join(f"all:{_escape_arxiv_term(t)}" for t in terms[:10])


def _escape_arxiv_term(term: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "", term) or "LLM"


def _score(source: str, year: int, citations: int, title: str, abstract: str) -> int:
    text = f"{title} {abstract}".lower()
    score = 0
    if source in {"arXiv direct", "Semantic Scholar"}:
        score += 2
    if year >= 2022:
        score += 1
    if citations >= 100:
        score += 3
    elif citations >= 25:
        score += 2
    elif citations > 0:
        score += 1
    for term in (
        "agent",
        "tool",
        "api",
        "function call",
        "reflection",
        "self-correct",
        "self refine",
        "reflexion",
        "recovery",
        "failure",
        "benchmark",
    ):
        if term in text:
            score += 1
    return score
