"""
Fetch latest AI/ML papers from arXiv and HuggingFace.

Adapted from ClaWHub daily-paper-digest (qjymary).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta

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
        hf_papers = await _fetch_huggingface(max_results)
        papers.extend(hf_papers)

    if not papers:
        # Fallback: search arXiv with a default query
        if not query:
            papers = await _search_arxiv("large language model agents", max_results)

    # Deduplicate by title
    seen = set()
    unique = []
    for p in papers:
        key = p["title"].lower().strip()
        if key not in seen:
            seen.add(key)
            unique.append(p)

    # Limit total
    unique = unique[:max_results]

    if not unique:
        return "No papers found."

    # Format as structured text for the LLM
    lines = [f"Found {len(unique)} papers:\n"]
    for i, p in enumerate(unique, 1):
        lines.append(f"## {i}. {p['title']}")
        lines.append(f"**Authors**: {p.get('authors', 'Unknown')}")
        lines.append(f"**Source**: {p.get('source', 'Unknown')}")
        if p.get("url"):
            lines.append(f"**URL**: {p['url']}")
        if p.get("abstract"):
            abstract = p["abstract"]
            if len(abstract) > 400:
                abstract = abstract[:400] + "..."
            lines.append(f"**Abstract**: {abstract}")
        lines.append("")

    return "\n".join(lines)


async def _search_arxiv(query: str, max_results: int) -> list[dict]:
    """Search arXiv using their API."""
    import httpx

    try:
        url = "http://export.arxiv.org/api/query"
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()

        # Parse Atom XML
        import xml.etree.ElementTree as ET
        root = ET.fromstring(resp.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        papers = []
        for entry in root.findall("atom:entry", ns):
            title = entry.findtext("atom:title", "", ns).strip().replace("\n", " ")
            abstract = entry.findtext("atom:summary", "", ns).strip().replace("\n", " ")
            authors = ", ".join(
                a.findtext("atom:name", "", ns)
                for a in entry.findall("atom:author", ns)
            )
            link = ""
            for l in entry.findall("atom:link", ns):
                if l.get("type") == "text/html":
                    link = l.get("href", "")
                    break
            if not link:
                link_el = entry.find("atom:id", ns)
                link = link_el.text if link_el is not None else ""

            papers.append({
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "url": link,
                "source": "arXiv",
            })

        return papers

    except Exception as exc:
        logger.warning("arXiv search failed: %s", exc)
        return []


async def _fetch_huggingface(max_results: int) -> list[dict]:
    """Fetch trending papers from HuggingFace daily papers page."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            # HF has a papers API
            resp = await client.get("https://huggingface.co/api/daily_papers")
            resp.raise_for_status()

        data = resp.json()
        papers = []
        for item in data[:max_results]:
            paper = item.get("paper", {})
            title = paper.get("title", "Untitled")
            abstract = paper.get("summary", "")
            authors = ", ".join(
                a.get("name", "") for a in paper.get("authors", [])[:5]
            )
            paper_id = paper.get("id", "")
            url = f"https://huggingface.co/papers/{paper_id}" if paper_id else ""

            papers.append({
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "url": url,
                "source": "HuggingFace Daily",
            })

        return papers

    except Exception as exc:
        logger.warning("HuggingFace papers fetch failed: %s", exc)
        return []
