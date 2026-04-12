from __future__ import annotations
import os, logging, httpx

logger = logging.getLogger(__name__)
_BASE = "https://api.semanticscholar.org/graph/v1"


async def execute(query: str, max_results: int = 10, year_from: int = 0, venues: str = "") -> str:
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    params = {
        "query": query,
        "limit": min(max_results * 3, 100),  # fetch extra for venue filtering
        "fields": "title,authors,year,venue,abstract,citationCount,url,publicationDate",
    }
    if year_from:
        params["year"] = f"{year_from}-"

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{_BASE}/paper/search", params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"Semantic Scholar search failed: {exc}"

    papers = data.get("data", [])

    # Client-side venue filter
    venue_filter = [v.strip().lower() for v in venues.split(",") if v.strip()] if venues else []
    if venue_filter:
        papers = [p for p in papers if any(v in (p.get("venue") or "").lower() for v in venue_filter)]

    papers = papers[:max_results]
    if not papers:
        return f"No papers found on Semantic Scholar for: {query}"

    lines = [f"**Semantic Scholar** — {len(papers)} papers for \"{query}\":\n"]
    for i, p in enumerate(papers, 1):
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:4])
        abstract = (p.get("abstract") or "")[:300]
        if len(p.get("abstract") or "") > 300:
            abstract += "..."
        venue = p.get("venue") or "Unknown venue"
        cites = p.get("citationCount", 0)
        url = p.get("url") or ""
        lines.append(f"## {i}. {p.get('title', 'Untitled')}")
        lines.append(f"**Authors**: {authors}")
        lines.append(f"**Venue**: {venue} ({p.get('year', '?')}) | **Citations**: {cites}")
        if url:
            lines.append(f"**URL**: {url}")
        if abstract:
            lines.append(f"**Abstract**: {abstract}")
        lines.append("")

    return "\n".join(lines)
