from __future__ import annotations
import os, logging, httpx

logger = logging.getLogger(__name__)
_BASE = "https://api.openalex.org"


async def execute(query: str, max_results: int = 10, year_from: int = 0, venue_type: str = "any") -> str:
    api_key = os.environ.get("OPENALEX_API_KEY", "")

    params: dict = {
        "search": query,
        "per-page": min(max_results, 50),
        "sort": "publication_year:desc",
    }
    if api_key:
        params["api_key"] = api_key

    filters = []
    if year_from:
        filters.append(f"publication_year:>{year_from - 1}")
    if venue_type == "conference":
        filters.append("primary_location.source.type:conference")
    elif venue_type == "journal":
        filters.append("primary_location.source.type:journal")
    if filters:
        params["filter"] = ",".join(filters)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{_BASE}/works", params=params)
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        return f"OpenAlex search failed: {exc}"

    works = data.get("results", [])
    if not works:
        return f"No papers found on OpenAlex for: {query}"

    lines = [f"**OpenAlex** — {len(works)} papers for \"{query}\":\n"]
    for i, w in enumerate(works[:max_results], 1):
        title = w.get("title", "Untitled")
        year = w.get("publication_year", "?")
        cited = w.get("cited_by_count", 0)
        doi = w.get("doi") or ""

        # Authors
        authorships = w.get("authorships") or []
        authors = ", ".join(
            a.get("author", {}).get("display_name", "") for a in authorships[:4]
        )

        # Venue
        loc = w.get("primary_location") or {}
        source = loc.get("source") or {}
        venue = source.get("display_name") or "Unknown venue"

        # Abstract (OpenAlex stores as inverted index — reconstruct)
        abstract = _reconstruct_abstract(w.get("abstract_inverted_index"))

        lines.append(f"## {i}. {title}")
        lines.append(f"**Authors**: {authors}")
        lines.append(f"**Venue**: {venue} ({year}) | **Citations**: {cited}")
        if doi:
            lines.append(f"**DOI**: {doi}")
        if abstract:
            lines.append(f"**Abstract**: {abstract[:300]}{'...' if len(abstract) > 300 else ''}")
        lines.append("")

    return "\n".join(lines)


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]}. Reconstruct to text."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)
