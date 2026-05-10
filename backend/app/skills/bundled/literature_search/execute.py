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
    year_from: int = 2022,
    max_results: int = 12,
    include_semantic_scholar: bool = False,
) -> str:
    q = (query or "").strip()
    if not q:
        return "Error: query must be non-empty."

    limit = max(1, min(int(max_results or 12), MAX_RESULTS))
    year = int(year_from or 2022)
    notes: list[str] = []

    async with httpx.AsyncClient(timeout=TIMEOUT, headers={"User-Agent": "Orchid literature_search/0.1"}) as client:
        tasks = [
            _search_arxiv(client, q, year, limit),
            _search_openalex(client, q, year, limit),
        ]
        if include_semantic_scholar and os.environ.get("SEMANTIC_SCHOLAR_API_KEY"):
            tasks.append(_search_semantic_scholar(client, q, year, limit))
        elif include_semantic_scholar:
            notes.append("Skipped Semantic Scholar: SEMANTIC_SCHOLAR_API_KEY is not configured.")
        else:
            notes.append("Skipped Semantic Scholar by default to avoid unauthenticated 429 rate limits.")

        groups = await asyncio.gather(*tasks, return_exceptions=True)

    papers: list[dict[str, Any]] = []
    for group in groups:
        if isinstance(group, Exception):
            notes.append(f"Source error: {type(group).__name__}: {group}")
            continue
        papers.extend(group)

    deduped = _dedupe(papers)[:limit]
    return _format_report(q, year, deduped, notes)


async def _search_arxiv(client: httpx.AsyncClient, query: str, year_from: int, limit: int) -> list[dict[str, Any]]:
    resp = await client.get(
        "https://export.arxiv.org/api/query",
        params={
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        },
    )
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
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
            "source": "arXiv",
            "title": title,
            "year": year or "",
            "venue": "arXiv",
            "authors": authors,
            "url": url,
            "abstract": abstract,
            "signal": "recent preprint",
        })
    return papers


async def _search_openalex(client: httpx.AsyncClient, query: str, year_from: int, limit: int) -> list[dict[str, Any]]:
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
        authors = ", ".join(
            ((a.get("author") or {}).get("display_name") or "")
            for a in (item.get("authorships") or [])[:4]
        )
        papers.append({
            "source": "OpenAlex",
            "title": item.get("display_name", ""),
            "year": item.get("publication_year", ""),
            "venue": source.get("display_name") or "OpenAlex",
            "authors": authors,
            "url": landing,
            "abstract": _openalex_abstract(item.get("abstract_inverted_index")),
            "signal": f"{item.get('cited_by_count', 0)} citations",
        })
    return papers


async def _search_semantic_scholar(client: httpx.AsyncClient, query: str, year_from: int, limit: int) -> list[dict[str, Any]]:
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
        }]
    resp.raise_for_status()
    data = resp.json()
    papers: list[dict[str, Any]] = []
    for item in data.get("data", []):
        authors = ", ".join((a.get("name") or "") for a in (item.get("authors") or [])[:4])
        papers.append({
            "source": "Semantic Scholar",
            "title": item.get("title", ""),
            "year": item.get("year", ""),
            "venue": item.get("venue") or "Semantic Scholar",
            "authors": authors,
            "url": item.get("url", ""),
            "abstract": item.get("abstract") or "",
            "signal": f"{item.get('citationCount', 0)} citations",
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


def _format_report(query: str, year_from: int, papers: list[dict[str, Any]], notes: list[str]) -> str:
    lines = [
        f"# Literature search: {query}",
        "",
        f"Filters: year_from={year_from}; sources=arXiv + OpenAlex by default.",
        "",
    ]
    if notes:
        lines.append("## Notes")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")

    lines.append("## Results")
    if not papers:
        lines.append("No results found.")
        return "\n".join(lines)

    for i, paper in enumerate(papers, 1):
        abstract = _clean(str(paper.get("abstract", "")))[:450]
        lines.extend([
            f"{i}. **{paper.get('title', '')}** ({paper.get('year', 'n.d.')})",
            f"   - Source: {paper.get('source', '')}; venue: {paper.get('venue', '')}; signal: {paper.get('signal', '')}",
            f"   - Authors: {paper.get('authors', '') or 'unknown'}",
            f"   - URL: {paper.get('url', '')}",
            f"   - Abstract: {abstract or 'not available'}",
        ])
    return "\n".join(lines)


def _clean(text: str) -> str:
    return " ".join((text or "").split())
