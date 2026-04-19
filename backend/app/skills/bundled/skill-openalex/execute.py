from __future__ import annotations
import logging
import os
import re

import httpx

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

    rows = []
    for w in works[:max_results]:
        loc = w.get("primary_location") or {}
        source = loc.get("source") or {}
        rows.append({
            "title": w.get("title", "Untitled"),
            "authors": ", ".join(
                a.get("author", {}).get("display_name", "")
                for a in (w.get("authorships") or [])[:4]
            ),
            "venue": source.get("display_name") or "",
            "year": w.get("publication_year", "") or "",
            "citations": w.get("cited_by_count", 0),
            "url": w.get("doi") or "",
            "abstract": _reconstruct_abstract(w.get("abstract_inverted_index")),
        })
    return _render_compact(rows, header=f"OpenAlex — {len(rows)} papers for \"{query}\"")


def _reconstruct_abstract(inverted_index: dict | None) -> str:
    """OpenAlex abstracts come as {word: [positions]}. Reverse to plain text."""
    if not inverted_index:
        return ""
    word_positions: list[tuple[int, str]] = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def _truncate_sentence(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    matches = list(_SENTENCE_END.finditer(cut))
    if matches and matches[-1].end() > max_chars * 0.6:
        return cut[:matches[-1].end()].rstrip()
    w = cut.rfind(" ")
    return (cut[:w] if w > 0 else cut).rstrip() + "…"


def _render_compact(papers: list[dict], header: str, abstract_chars: int = 280) -> str:
    lines = [header, ""]
    for i, p in enumerate(papers, 1):
        meta_bits = [b for b in (p.get("venue", ""), str(p.get("year") or "") if p.get("year") else "") if b]
        meta = " ".join(meta_bits)
        if p.get("citations") is not None:
            meta += f" · {p['citations']} cites" if meta else f"{p['citations']} cites"
        head = f"[{i}] {p.get('title', 'Untitled')}"
        if p.get("authors"):
            head += f" — {p['authors']}"
        if meta:
            head += f" — {meta}"
        lines.append(head)
        if p.get("url"):
            lines.append(f"    {p['url']}")
        if p.get("abstract"):
            lines.append(f"    {_truncate_sentence(p['abstract'], abstract_chars)}")
        lines.append("")
    return "\n".join(lines)
