"""arxiv_search — query arxiv's public Atom API."""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_API = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


async def execute(
    query: str,
    max_results: int = 10,
    year_from: int | None = None,
    sort_by: str = "submitted_date",
) -> str:
    max_results = max(1, min(int(max_results), 50))
    sort_param = "submittedDate" if sort_by == "submitted_date" else "relevance"

    params = {
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": sort_param,
        "sortOrder": "descending",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(f"{_API}?{urlencode(params)}")
            resp.raise_for_status()
    except Exception as exc:
        logger.error("arxiv_search HTTP error: %s", exc)
        return f"arxiv_search failed: {exc}"

    try:
        root = ET.fromstring(resp.text)
    except ET.ParseError as exc:
        return f"arxiv_search: malformed Atom response ({exc})"

    entries = root.findall("atom:entry", _NS)
    if not entries:
        return f"arxiv_search: no results for {query!r}."

    items: list[str] = []
    for entry in entries:
        published = (entry.findtext("atom:published", default="", namespaces=_NS) or "")[:10]
        if year_from and published:
            try:
                if int(published[:4]) < int(year_from):
                    continue
            except ValueError:
                pass

        title = (entry.findtext("atom:title", default="", namespaces=_NS) or "").strip()
        title = re.sub(r"\s+", " ", title)

        abstract = (entry.findtext("atom:summary", default="", namespaces=_NS) or "").strip()
        abstract = re.sub(r"\s+", " ", abstract)
        if len(abstract) > 600:
            abstract = abstract[:600].rstrip() + "…"

        authors = [
            (a.findtext("atom:name", default="", namespaces=_NS) or "").strip()
            for a in entry.findall("atom:author", _NS)
        ]
        authors = [a for a in authors if a][:4]
        author_str = ", ".join(authors) + (" et al." if len(entry.findall("atom:author", _NS)) > 4 else "")

        # Find the abs URL (links of rel="alternate" and type="text/html")
        url = ""
        for link in entry.findall("atom:link", _NS):
            if link.get("rel") == "alternate" and link.get("type") == "text/html":
                url = link.get("href", "")
                break
        if not url:
            # Fallback to <id> which is the arxiv abs URL
            url = entry.findtext("atom:id", default="", namespaces=_NS).strip()

        primary_cat = ""
        cat_el = entry.find("arxiv:primary_category", _NS)
        if cat_el is not None:
            primary_cat = cat_el.get("term", "")

        items.append(
            f"**{title}** ({published})\n"
            f"  {author_str}{' · ' + primary_cat if primary_cat else ''}\n"
            f"  {url}\n"
            f"  {abstract}"
        )

    if not items:
        return f"arxiv_search: no results for {query!r} matching year_from={year_from}."
    header = f"arxiv_search — {len(items)} result(s) for {query!r}"
    if year_from:
        header += f" (year ≥ {year_from})"
    return header + ":\n\n" + "\n\n".join(items)
