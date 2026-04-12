from __future__ import annotations
import logging, httpx

logger = logging.getLogger(__name__)
_BASE = "https://dblp.org/search/publ/api"


async def execute(query: str, max_results: int = 10, venue: str = "") -> str:
    search_query = query
    if venue:
        search_query = f"{query} venue:{venue}"

    params = {
        "q": search_query,
        "format": "json",
        "h": min(max_results, 100),
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"DBLP search failed: {exc}"

    result = data.get("result", {})
    hits = result.get("hits", {}).get("hit", [])
    if not hits:
        return f"No papers found on DBLP for: {search_query}"

    lines = [f"**DBLP** — {len(hits)} papers for \"{search_query}\":\n"]
    for i, hit in enumerate(hits[:max_results], 1):
        info = hit.get("info", {})
        title = info.get("title", "Untitled")
        year = info.get("year", "?")
        venue_name = info.get("venue", "Unknown")
        url = info.get("url", "")
        doi = info.get("doi", "")

        # Authors — can be string or list
        authors_raw = info.get("authors", {}).get("author", [])
        if isinstance(authors_raw, dict):
            authors_raw = [authors_raw]
        if isinstance(authors_raw, list):
            authors = ", ".join(
                a.get("text", a) if isinstance(a, dict) else str(a)
                for a in authors_raw[:4]
            )
        else:
            authors = str(authors_raw)

        lines.append(f"## {i}. {title}")
        lines.append(f"**Authors**: {authors}")
        lines.append(f"**Venue**: {venue_name} ({year})")
        if url:
            lines.append(f"**URL**: {url}")
        if doi:
            lines.append(f"**DOI**: {doi}")
        lines.append("")

    return "\n".join(lines)
