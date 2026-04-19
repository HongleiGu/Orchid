"""
Fetch latest AI/ML papers from arXiv and HuggingFace.

Adapted from ClaWHub daily-paper-digest (qjymary).
"""
from __future__ import annotations

import logging
import re

logger = logging.getLogger(__name__)


async def execute(
    query: str = "",
    max_results: int = 5,
    source: str = "both",
) -> str:
    papers: list[dict] = []

    if source in ("arxiv", "both") and query:
        papers.extend(await _search_arxiv(query, max_results))

    if source in ("huggingface", "both"):
        papers.extend(await _fetch_huggingface(max_results))

    if not papers and not query:
        papers = await _search_arxiv("large language model agents", max_results)

    seen: set[str] = set()
    unique: list[dict] = []
    for p in papers:
        key = p["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(p)
    unique = unique[:max_results]

    if not unique:
        return "No papers found."

    return _render_compact(unique, header=f"arXiv/HF — {len(unique)} papers" + (f" for \"{query}\"" if query else ""))


async def _search_arxiv(query: str, max_results: int) -> list[dict]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "http://export.arxiv.org/api/query",
                params={
                    "search_query": f"all:{query}",
                    "start": 0,
                    "max_results": max_results,
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
                a.findtext("atom:name", "", ns)
                for a in entry.findall("atom:author", ns)[:4]
            )
            link = ""
            for l in entry.findall("atom:link", ns):
                if l.get("type") == "text/html":
                    link = l.get("href", "")
                    break
            if not link:
                link_el = entry.find("atom:id", ns)
                link = link_el.text if link_el is not None else ""

            year = (entry.findtext("atom:published", "", ns) or "")[:4]
            papers.append({
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "url": link,
                "venue": "arXiv",
                "year": year,
            })
        return papers
    except Exception as exc:
        logger.warning("arXiv search failed: %s", exc)
        return []


async def _fetch_huggingface(max_results: int) -> list[dict]:
    import httpx
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get("https://huggingface.co/api/daily_papers")
            resp.raise_for_status()
        data = resp.json()
        papers = []
        for item in data[:max_results]:
            paper = item.get("paper", {})
            paper_id = paper.get("id", "")
            papers.append({
                "title": paper.get("title", "Untitled"),
                "authors": ", ".join(a.get("name", "") for a in paper.get("authors", [])[:4]),
                "abstract": paper.get("summary", ""),
                "url": f"https://huggingface.co/papers/{paper_id}" if paper_id else "",
                "venue": "HF Daily",
                "year": (paper.get("publishedAt", "") or "")[:4],
            })
        return papers
    except Exception as exc:
        logger.warning("HuggingFace papers fetch failed: %s", exc)
        return []


# ── Compact rendering (shared shape across paper fetchers) ──────────────────

_SENTENCE_END = re.compile(r"[.!?](?:\s|$)")


def _truncate_sentence(text: str, max_chars: int) -> str:
    """Cut at sentence boundary near max_chars; never mid-word."""
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    matches = list(_SENTENCE_END.finditer(cut))
    if matches and matches[-1].end() > max_chars * 0.6:
        return cut[:matches[-1].end()].rstrip()
    w = cut.rfind(" ")
    return (cut[:w] if w > 0 else cut).rstrip() + "…"


def _render_compact(papers: list[dict], header: str, abstract_chars: int = 280) -> str:
    """One paper = 3 lines: title/meta, url, abstract. Saves ~30% vs heavy markdown."""
    lines = [header, ""]
    for i, p in enumerate(papers, 1):
        title = p.get("title", "Untitled")
        authors = p.get("authors", "")
        venue = p.get("venue", "")
        year = p.get("year", "")
        cites = p.get("citations")

        meta_bits = [b for b in (venue, str(year) if year else "") if b]
        meta = " ".join(meta_bits)
        if cites is not None:
            meta += f" · {cites} cites" if meta else f"{cites} cites"

        head = f"[{i}] {title}"
        if authors:
            head += f" — {authors}"
        if meta:
            head += f" — {meta}"
        lines.append(head)

        if p.get("url"):
            lines.append(f"    {p['url']}")
        if p.get("abstract"):
            lines.append(f"    {_truncate_sentence(p['abstract'], abstract_chars)}")
        lines.append("")
    return "\n".join(lines)
