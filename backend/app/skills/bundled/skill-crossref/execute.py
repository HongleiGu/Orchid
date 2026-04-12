from __future__ import annotations
import logging, httpx

logger = logging.getLogger(__name__)
_BASE = "https://api.crossref.org/v1/works"


async def execute(query: str, max_results: int = 10, year_from: int = 0, type: str = "any") -> str:
    params: dict = {
        "query": query,
        "rows": min(max_results, 50),
        "sort": "published",
        "order": "desc",
        "mailto": "orchid-bot@example.com",  # polite pool
    }

    filters = []
    if year_from:
        filters.append(f"from-pub-date:{year_from}-01-01")
    if type != "any":
        filters.append(f"type:{type}")
    filters.append("has-abstract:true")
    if filters:
        params["filter"] = ",".join(filters)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(_BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"CrossRef search failed: {exc}"

    items = data.get("message", {}).get("items", [])
    if not items:
        return f"No papers found on CrossRef for: {query}"

    lines = [f"**CrossRef** — {len(items)} papers for \"{query}\":\n"]
    for i, item in enumerate(items[:max_results], 1):
        title_parts = item.get("title", ["Untitled"])
        title = title_parts[0] if title_parts else "Untitled"

        # Authors
        authors_raw = item.get("author", [])
        authors = ", ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in authors_raw[:4]
        )

        # Year
        pub_date = item.get("published", {}).get("date-parts", [[None]])
        year = pub_date[0][0] if pub_date and pub_date[0] else "?"

        # Venue
        container = item.get("container-title", [])
        venue = container[0] if container else "Unknown"

        cited = item.get("is-referenced-by-count", 0)
        doi = item.get("DOI", "")
        abstract = item.get("abstract", "")
        # CrossRef abstracts often have XML tags
        import re
        abstract = re.sub(r"<[^>]+>", "", abstract)

        lines.append(f"## {i}. {title}")
        lines.append(f"**Authors**: {authors}")
        lines.append(f"**Venue**: {venue} ({year}) | **Citations**: {cited}")
        if doi:
            lines.append(f"**DOI**: https://doi.org/{doi}")
        if abstract:
            lines.append(f"**Abstract**: {abstract[:300]}{'...' if len(abstract) > 300 else ''}")
        lines.append("")

    return "\n".join(lines)
