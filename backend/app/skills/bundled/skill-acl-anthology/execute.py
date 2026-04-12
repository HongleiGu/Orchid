"""
ACL Anthology search — uses the Semantic Scholar API filtered to ACL venues,
since ACL Anthology doesn't have a REST search API.

This is a pragmatic approach: Semantic Scholar indexes all ACL papers and
we can filter by venue name.
"""
from __future__ import annotations
import os, logging, httpx

logger = logging.getLogger(__name__)
_BASE = "https://api.semanticscholar.org/graph/v1"

# ACL Anthology venue names as they appear in Semantic Scholar
_ACL_VENUES = {
    "acl": "ACL",
    "emnlp": "EMNLP",
    "naacl": "NAACL",
    "eacl": "EACL",
    "conll": "CoNLL",
    "findings": "Findings",
    "tacl": "Transactions of the Association for Computational Linguistics",
    "cl": "Computational Linguistics",
}


async def execute(query: str, max_results: int = 10, venue: str = "") -> str:
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {}
    if api_key:
        headers["x-api-key"] = api_key

    # Search with venue hint in query for better results
    search_query = query
    venue_filter = ""
    if venue:
        venue_lower = venue.lower()
        venue_name = _ACL_VENUES.get(venue_lower, venue)
        search_query = f"{query} {venue_name}"
        venue_filter = venue_name.lower()
    else:
        # Default: filter to any ACL venue
        venue_filter = ""

    params = {
        "query": search_query,
        "limit": min(max_results * 5, 100),  # fetch extra for filtering
        "fields": "title,authors,year,venue,abstract,citationCount,url,externalIds",
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{_BASE}/paper/search", params=params, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"ACL Anthology search failed: {exc}"

    papers = data.get("data", [])

    # Filter to ACL venues
    if venue_filter:
        papers = [p for p in papers if venue_filter in (p.get("venue") or "").lower()]
    else:
        # Filter to any known ACL venue
        acl_names = [v.lower() for v in _ACL_VENUES.values()]
        papers = [
            p for p in papers
            if any(av in (p.get("venue") or "").lower() for av in acl_names)
        ]

    papers = papers[:max_results]
    if not papers:
        return f"No ACL Anthology papers found for: {query}"

    lines = [f"**ACL Anthology** — {len(papers)} papers for \"{query}\":\n"]
    for i, p in enumerate(papers, 1):
        authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:4])
        abstract = (p.get("abstract") or "")[:300]
        if len(p.get("abstract") or "") > 300:
            abstract += "..."
        venue_name = p.get("venue") or "ACL"
        cites = p.get("citationCount", 0)

        # Try to get ACL Anthology URL from external IDs
        ext = p.get("externalIds") or {}
        acl_id = ext.get("ACL", "")
        url = f"https://aclanthology.org/{acl_id}" if acl_id else (p.get("url") or "")

        lines.append(f"## {i}. {p.get('title', 'Untitled')}")
        lines.append(f"**Authors**: {authors}")
        lines.append(f"**Venue**: {venue_name} ({p.get('year', '?')}) | **Citations**: {cites}")
        if url:
            lines.append(f"**URL**: {url}")
        if abstract:
            lines.append(f"**Abstract**: {abstract}")
        lines.append("")

    return "\n".join(lines)
