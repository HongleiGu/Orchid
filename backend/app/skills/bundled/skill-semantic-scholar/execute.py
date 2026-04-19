from __future__ import annotations
import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)
_BASE = "https://api.semanticscholar.org/graph/v1"


async def execute(query: str, max_results: int = 10, year_from: int = 0, venues: str = "") -> str:
    api_key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    headers = {"x-api-key": api_key} if api_key else {}

    params = {
        "query": query,
        # Fetch extra so client-side venue filter still has options
        "limit": min(max_results * 3, 100),
        "fields": "title,authors,year,venue,abstract,citationCount,url",
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
    venue_filter = [v.strip().lower() for v in venues.split(",") if v.strip()] if venues else []
    if venue_filter:
        papers = [p for p in papers if any(v in (p.get("venue") or "").lower() for v in venue_filter)]
    papers = papers[:max_results]

    if not papers:
        return f"No papers found on Semantic Scholar for: {query}"

    rows = [
        {
            "title": p.get("title", "Untitled"),
            "authors": ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:4]),
            "venue": p.get("venue") or "",
            "year": p.get("year") or "",
            "citations": p.get("citationCount", 0),
            "url": p.get("url") or "",
            "abstract": p.get("abstract") or "",
        }
        for p in papers
    ]
    return _render_compact(rows, header=f"Semantic Scholar — {len(rows)} papers for \"{query}\"")


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
