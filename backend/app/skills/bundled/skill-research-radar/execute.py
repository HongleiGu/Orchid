"""
Research Radar — broad direction spotting across configurable academic sources.

Sources:
  arxiv              — recent papers by submission date
  semantic_scholar   — citation velocity (trending academically)
  openalex           — broad coverage, venue/concept filtering
  dblp               — top CS venues (NeurIPS, ICLR, ICML etc)
  crossref           — DOI-level, proceedings articles
  acl                — NLP conferences (ACL, EMNLP, NAACL)
  huggingface_papers — community-curated trending
  huggingface_models — trending model uploads (adoption signals)
  papers_with_code   — SOTA benchmark movements
"""
from __future__ import annotations

import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 12

ALL_SOURCES = [
    "arxiv", "semantic_scholar", "openalex", "dblp", "crossref",
    "acl", "huggingface_papers", "huggingface_models", "papers_with_code",
]

BREADTH_EXPANSIONS = {
    "focused": [],
    "broad": ["{field} survey", "{field} benchmark"],
    "exploratory": ["{field} survey", "{field} benchmark", "{field} alternative approach"],
}


async def execute(
    field: str,
    time_window: str = "month",
    breadth: str = "broad",
    max_results_per_source: int = 5,
    sources: str = "all",
    venues: str = "",
) -> str:
    n = max_results_per_source

    # Parse source selection
    if sources.strip().lower() == "all":
        active = set(ALL_SOURCES)
    else:
        active = {s.strip().lower() for s in sources.split(",") if s.strip()}

    # Breadth queries
    queries = [field]
    for t in BREADTH_EXPANSIONS.get(breadth, []):
        queries.append(t.format(field=field))

    venue_list = [v.strip() for v in venues.split(",") if v.strip()]

    all_papers: list[dict] = []
    source_counts: dict[str, int] = {}

    # ── Fetch from each active source ────────────────────────────────────────

    if "arxiv" in active:
        for q in queries[:3]:
            all_papers.extend(await _arxiv(q, n))
        source_counts["arXiv"] = len([p for p in all_papers if p["source"] == "arXiv"])

    if "semantic_scholar" in active:
        papers = await _semantic_scholar(field, n, time_window)
        all_papers.extend(papers)
        source_counts["Semantic Scholar"] = len(papers)

    if "openalex" in active:
        papers = await _openalex(field, n, time_window, venue_list)
        all_papers.extend(papers)
        source_counts["OpenAlex"] = len(papers)

    if "dblp" in active:
        if venue_list:
            papers = []
            for venue in venue_list[:4]:
                papers.extend(await _dblp(field, n, venue))
        else:
            papers = await _dblp(field, n, "")
        all_papers.extend(papers)
        source_counts["DBLP"] = len(papers)

    if "crossref" in active:
        papers = await _crossref(field, n, time_window)
        all_papers.extend(papers)
        source_counts["CrossRef"] = len(papers)

    if "acl" in active:
        papers = await _acl(field, n)
        all_papers.extend(papers)
        source_counts["ACL Anthology"] = len(papers)

    if "huggingface_papers" in active:
        papers = await _hf_papers(n)
        all_papers.extend(papers)
        source_counts["HuggingFace Papers"] = len(papers)

    if "huggingface_models" in active:
        papers = await _hf_models(field, n)
        all_papers.extend(papers)
        source_counts["HuggingFace Models"] = len(papers)

    if "papers_with_code" in active:
        papers = await _pwc(field, n)
        all_papers.extend(papers)
        source_counts["Papers With Code"] = len(papers)

    unique = _deduplicate(all_papers)
    return _build_report(field, time_window, breadth, unique, source_counts, active)


# ── Source fetchers ──────────────────────────────────────────────────────────

async def _arxiv(query: str, limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "http://export.arxiv.org/api/query",
                params={"search_query": f"all:{query}", "max_results": limit,
                        "sortBy": "submittedDate", "sortOrder": "descending"},
            )
            resp.raise_for_status()

        root = ET.fromstring(resp.text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        papers = []
        for e in root.findall("a:entry", ns):
            title = e.findtext("a:title", "", ns).strip().replace("\n", " ")
            abstract = e.findtext("a:summary", "", ns).strip().replace("\n", " ")[:300]
            authors = ", ".join(a.findtext("a:name", "", ns) for a in e.findall("a:author", ns))[:200]
            url = ""
            for l in e.findall("a:link", ns):
                if l.get("type") == "text/html":
                    url = l.get("href", ""); break
            if not url:
                id_el = e.find("a:id", ns)
                url = id_el.text if id_el is not None else ""
            papers.append({"title": title, "authors": authors, "abstract": abstract,
                           "url": url, "source": "arXiv", "signal": "recent"})
        return papers
    except Exception as exc:
        logger.warning("arXiv failed: %s", exc); return []


async def _semantic_scholar(query: str, limit: int, time_window: str) -> list[dict]:
    year = {"week": datetime.now().year, "month": datetime.now().year,
            "quarter": datetime.now().year - 1}.get(time_window, datetime.now().year)
    headers = {}
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    if key:
        headers["x-api-key"] = key
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": query, "limit": limit * 2, "year": f"{year}-",
                        "fields": "title,abstract,url,authors,year,citationCount,influentialCitationCount,venue"},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        raw = sorted(data.get("data", []),
                     key=lambda p: (p.get("influentialCitationCount", 0), p.get("citationCount", 0)),
                     reverse=True)
        papers = []
        for p in raw[:limit]:
            authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3])
            c = p.get("citationCount", 0)
            abstract = (p.get("abstract") or "")[:300]
            venue = p.get("venue") or ""
            papers.append({"title": p.get("title", ""), "authors": authors,
                           "abstract": f"[{venue}, {c} cites] {abstract}",
                           "url": p.get("url", ""), "source": "Semantic Scholar",
                           "signal": f"{c} citations"})
        return papers
    except Exception as exc:
        logger.warning("Semantic Scholar failed: %s", exc); return []


async def _openalex(query: str, limit: int, time_window: str, venue_filter: list[str]) -> list[dict]:
    year = {"week": datetime.now().year, "month": datetime.now().year,
            "quarter": datetime.now().year - 1}.get(time_window, datetime.now().year)
    params: dict = {"search": query, "per-page": min(limit, 50), "sort": "publication_year:desc"}
    key = os.environ.get("OPENALEX_API_KEY", "")
    if key:
        params["api_key"] = key
    filters = [f"publication_year:>{year - 1}"]
    if venue_filter:
        # OpenAlex doesn't have a direct venue name filter, so we just add to search
        pass
    params["filter"] = ",".join(filters)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://api.openalex.org/works", params=params)
            resp.raise_for_status()
            data = resp.json()
        papers = []
        for w in data.get("results", [])[:limit]:
            title = w.get("title", "Untitled")
            year_pub = w.get("publication_year", "?")
            cited = w.get("cited_by_count", 0)
            authors = ", ".join(a.get("author", {}).get("display_name", "")
                                for a in (w.get("authorships") or [])[:3])
            loc = w.get("primary_location") or {}
            venue = (loc.get("source") or {}).get("display_name") or ""
            abstract = _openalex_abstract(w.get("abstract_inverted_index"))
            doi = w.get("doi") or ""
            papers.append({"title": title, "authors": authors,
                           "abstract": f"[{venue}, {cited} cites] {abstract[:250]}",
                           "url": doi or "", "source": "OpenAlex",
                           "signal": f"{venue} ({year_pub})"})
        return papers
    except Exception as exc:
        logger.warning("OpenAlex failed: %s", exc); return []


async def _dblp(query: str, limit: int, venue: str) -> list[dict]:
    q = f"{query} venue:{venue}" if venue else query
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://dblp.org/search/publ/api",
                                    params={"q": q, "format": "json", "h": limit})
            resp.raise_for_status()
            data = resp.json()
        papers = []
        for hit in data.get("result", {}).get("hits", {}).get("hit", [])[:limit]:
            info = hit.get("info", {})
            title = info.get("title", "Untitled")
            year = info.get("year", "?")
            v = info.get("venue", venue or "?")
            url = info.get("url", "")
            authors_raw = info.get("authors", {}).get("author", [])
            if isinstance(authors_raw, dict): authors_raw = [authors_raw]
            authors = ", ".join(
                a.get("text", a) if isinstance(a, dict) else str(a) for a in authors_raw[:3]
            )
            papers.append({"title": title, "authors": authors, "abstract": "",
                           "url": url, "source": "DBLP", "signal": f"{v} ({year})"})
        return papers
    except Exception as exc:
        logger.warning("DBLP failed: %s", exc); return []


async def _crossref(query: str, limit: int, time_window: str) -> list[dict]:
    import re
    year = {"week": datetime.now().year, "month": datetime.now().year,
            "quarter": datetime.now().year - 1}.get(time_window, datetime.now().year)
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://api.crossref.org/v1/works",
                                    params={"query": query, "rows": limit,
                                            "sort": "published", "order": "desc",
                                            "filter": f"from-pub-date:{year}-01-01,has-abstract:true",
                                            "mailto": "orchid-bot@example.com"})
            resp.raise_for_status()
            data = resp.json()
        papers = []
        for item in data.get("message", {}).get("items", [])[:limit]:
            title = (item.get("title") or ["Untitled"])[0]
            authors = ", ".join(f"{a.get('given', '')} {a.get('family', '')}".strip()
                                for a in (item.get("author") or [])[:3])
            container = (item.get("container-title") or [""])[0]
            cited = item.get("is-referenced-by-count", 0)
            doi = item.get("DOI", "")
            abstract = re.sub(r"<[^>]+>", "", item.get("abstract", ""))[:250]
            papers.append({"title": title, "authors": authors, "abstract": abstract,
                           "url": f"https://doi.org/{doi}" if doi else "",
                           "source": "CrossRef", "signal": f"{container}"})
        return papers
    except Exception as exc:
        logger.warning("CrossRef failed: %s", exc); return []


async def _acl(query: str, limit: int) -> list[dict]:
    headers = {}
    key = os.environ.get("SEMANTIC_SCHOLAR_API_KEY", "")
    if key:
        headers["x-api-key"] = key
    acl_venues = ["acl", "emnlp", "naacl", "eacl", "conll", "findings", "tacl"]
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={"query": query, "limit": limit * 5,
                        "fields": "title,abstract,url,authors,year,venue,citationCount,externalIds"},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        filtered = [p for p in data.get("data", [])
                    if any(v in (p.get("venue") or "").lower() for v in acl_venues)]
        papers = []
        for p in filtered[:limit]:
            authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3])
            venue = p.get("venue") or "ACL"
            abstract = (p.get("abstract") or "")[:250]
            ext = p.get("externalIds") or {}
            acl_id = ext.get("ACL", "")
            url = f"https://aclanthology.org/{acl_id}" if acl_id else (p.get("url") or "")
            papers.append({"title": p.get("title", ""), "authors": authors,
                           "abstract": abstract, "url": url,
                           "source": "ACL Anthology", "signal": venue})
        return papers
    except Exception as exc:
        logger.warning("ACL failed: %s", exc); return []


async def _hf_papers(limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://huggingface.co/api/daily_papers")
            resp.raise_for_status()
        papers = []
        for item in resp.json()[:limit]:
            p = item.get("paper", {})
            authors = ", ".join(a.get("name", "") for a in (p.get("authors") or [])[:3])
            pid = p.get("id", "")
            papers.append({"title": p.get("title", ""), "authors": authors,
                           "abstract": (p.get("summary") or "")[:300],
                           "url": f"https://huggingface.co/papers/{pid}" if pid else "",
                           "source": "HuggingFace Papers", "signal": "community trending"})
        return papers
    except Exception as exc:
        logger.warning("HF papers failed: %s", exc); return []


async def _hf_models(field: str, limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://huggingface.co/api/models",
                                    params={"search": field, "sort": "trending", "limit": limit})
            resp.raise_for_status()
        items = []
        for m in resp.json()[:limit]:
            mid = m.get("modelId", "")
            items.append({"title": f"Model: {mid}", "authors": m.get("author", ""),
                          "abstract": f"Downloads: {m.get('downloads', 0):,} | Likes: {m.get('likes', 0)} | Pipeline: {m.get('pipeline_tag', '?')}",
                          "url": f"https://huggingface.co/{mid}",
                          "source": "HuggingFace Models", "signal": f"{m.get('downloads', 0):,} downloads"})
        return items
    except Exception as exc:
        logger.warning("HF models failed: %s", exc); return []


async def _pwc(field: str, limit: int) -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get("https://paperswithcode.com/api/v1/papers/",
                                    params={"q": field, "items_per_page": limit})
            resp.raise_for_status()
        papers = []
        for p in resp.json().get("results", [])[:limit]:
            authors_raw = p.get("authors", [])
            authors = ", ".join(authors_raw[:3]) if isinstance(authors_raw, list) else ""
            papers.append({"title": p.get("title", ""), "authors": authors,
                           "abstract": (p.get("abstract") or "")[:300],
                           "url": p.get("url_abs", "") or p.get("paper_url", ""),
                           "source": "Papers With Code", "signal": "SOTA"})
        return papers
    except Exception as exc:
        logger.warning("PwC failed: %s", exc); return []


# ── Helpers ──────────────────────────────────────────────────────────────────

def _openalex_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = []
    for word, idxs in inverted_index.items():
        for i in idxs:
            positions.append((i, word))
    positions.sort()
    return " ".join(w for _, w in positions)


def _deduplicate(papers: list[dict]) -> list[dict]:
    seen: set[str] = set()
    unique: list[dict] = []
    for p in papers:
        key = p["title"].lower().strip()[:60]
        if key not in seen:
            seen.add(key)
            unique.append(p)
    return unique


def _build_report(
    field: str, time_window: str, breadth: str,
    papers: list[dict], source_counts: dict[str, int],
    active_sources: set[str],
) -> str:
    lines = [
        f"# Research Radar: {field}",
        f"**Window**: {time_window} | **Breadth**: {breadth} | **Unique items**: {len(papers)}",
        f"**Active sources**: {', '.join(sorted(active_sources))}",
        f"**Results per source**: {', '.join(f'{k}: {v}' for k, v in source_counts.items() if v > 0)}",
        "",
    ]

    by_source: dict[str, list[dict]] = {}
    for p in papers:
        by_source.setdefault(p["source"], []).append(p)

    for source, items in by_source.items():
        lines.append(f"## {source}")
        lines.append("")
        for p in items:
            title = p["title"]
            url = p.get("url", "")
            signal = p.get("signal", "")
            abstract = p.get("abstract", "")
            if url:
                lines.append(f"### [{title}]({url})")
            else:
                lines.append(f"### {title}")
            if p.get("authors"):
                lines.append(f"*{p['authors']}*")
            if signal:
                lines.append(f"**Signal**: {signal}")
            if abstract:
                lines.append(f"> {abstract}")
            lines.append("")

    return "\n".join(lines)
