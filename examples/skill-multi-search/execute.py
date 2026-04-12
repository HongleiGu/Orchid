"""
Multi-engine web search — no API keys required.

Searches DuckDuckGo, Brave, Bing, and Google simultaneously,
then aggregates and deduplicates results.

Adapted from ClaWHub gpyangyoujun/multi-search-engine.
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import quote_plus

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 12
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/json",
    "Accept-Language": "en-US,en;q=0.9",
}

ALL_ENGINES = ["duckduckgo", "brave", "bing", "google"]


async def execute(
    query: str,
    engines: str = "all",
    max_results: int = 10,
    time_filter: str = "any",
) -> str:
    active = set(ALL_ENGINES) if engines.strip().lower() == "all" else {
        e.strip().lower() for e in engines.split(",") if e.strip()
    }

    # Run all engines concurrently
    tasks = []
    if "duckduckgo" in active:
        tasks.append(_search_duckduckgo(query, time_filter))
    if "brave" in active:
        tasks.append(_search_brave(query, time_filter))
    if "bing" in active:
        tasks.append(_search_bing(query, time_filter))
    if "google" in active:
        tasks.append(_search_google(query, time_filter))

    results_lists = await asyncio.gather(*tasks, return_exceptions=True)

    # Flatten and tag source
    all_results: list[dict] = []
    engine_names = [e for e in ALL_ENGINES if e in active]
    for i, results in enumerate(results_lists):
        if isinstance(results, Exception):
            logger.warning("Engine %s failed: %s", engine_names[i] if i < len(engine_names) else "?", results)
            continue
        if isinstance(results, list):
            for r in results:
                r["engine"] = engine_names[i] if i < len(engine_names) else "unknown"
            all_results.extend(results)

    if not all_results:
        return f"No results found across any engine for: {query}"

    # Deduplicate by URL, keeping the first occurrence + counting cross-engine hits
    unique = _deduplicate_and_rank(all_results)
    unique = unique[:max_results]

    lines = [f"**Multi-Search** — {len(unique)} results for \"{query}\" (from {', '.join(active)}):\n"]
    for i, r in enumerate(unique, 1):
        engines_found = ", ".join(r.get("found_in", []))
        lines.append(f"### {i}. {r['title']}")
        lines.append(f"**URL**: {r['url']}")
        lines.append(f"**Engines**: {engines_found}")
        if r.get("snippet"):
            lines.append(f"> {r['snippet'][:300]}")
        lines.append("")

    return "\n".join(lines)


# ── Engine implementations ───────────────────────────────────────────────────

async def _search_duckduckgo(query: str, time_filter: str) -> list[dict]:
    """DuckDuckGo JSON API (instant answers + HTML fallback)."""
    results: list[dict] = []

    # Try JSON API first
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            )
            data = resp.json()

        if data.get("Abstract"):
            results.append({
                "title": data.get("Heading", query),
                "url": data.get("AbstractURL", ""),
                "snippet": data["Abstract"],
            })
        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:80],
                    "url": topic.get("FirstURL", ""),
                    "snippet": topic.get("Text", ""),
                })
    except Exception as exc:
        logger.debug("DDG JSON API failed: %s", exc)

    # HTML fallback for richer results
    if len(results) < 3:
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
                resp = await client.get(
                    "https://html.duckduckgo.com/html/",
                    params={"q": query},
                )
            results.extend(_parse_ddg_html(resp.text))
        except Exception as exc:
            logger.debug("DDG HTML failed: %s", exc)

    return results


async def _search_brave(query: str, time_filter: str) -> list[dict]:
    """Brave Search — scrape the HTML results page."""
    tf_map = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}
    params: dict = {"q": query}
    if time_filter in tf_map:
        params["tf"] = tf_map[time_filter]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get("https://search.brave.com/search", params=params)
        return _parse_brave_html(resp.text)
    except Exception as exc:
        logger.debug("Brave failed: %s", exc)
        return []


async def _search_bing(query: str, time_filter: str) -> list[dict]:
    """Bing — scrape HTML results."""
    params: dict = {"q": query}
    if time_filter == "day":
        params["filters"] = "ex1:\"ez1\""
    elif time_filter == "week":
        params["filters"] = "ex1:\"ez2\""
    elif time_filter == "month":
        params["filters"] = "ex1:\"ez3\""

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get("https://www.bing.com/search", params=params)
        return _parse_bing_html(resp.text)
    except Exception as exc:
        logger.debug("Bing failed: %s", exc)
        return []


async def _search_google(query: str, time_filter: str) -> list[dict]:
    """Google — scrape HTML results (lightweight, no JS)."""
    tf_map = {"day": "qdr:d", "week": "qdr:w", "month": "qdr:m", "year": "qdr:y"}
    params: dict = {"q": query, "hl": "en"}
    if time_filter in tf_map:
        params["tbs"] = tf_map[time_filter]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True) as client:
            resp = await client.get("https://www.google.com/search", params=params)
        return _parse_google_html(resp.text)
    except Exception as exc:
        logger.debug("Google failed: %s", exc)
        return []


# ── HTML parsers ─────────────────────────────────────────────────────────────

def _parse_ddg_html(html: str) -> list[dict]:
    results = []
    # DuckDuckGo HTML uses class="result__a" for links
    for match in re.finditer(
        r'class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</(?:a|span|td)',
        html, re.DOTALL
    ):
        url, title, snippet = match.group(1), match.group(2), match.group(3)
        title = re.sub(r"<[^>]+>", "", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        if url and title:
            results.append({"title": title, "url": url, "snippet": snippet})
    return results[:8]


def _parse_brave_html(html: str) -> list[dict]:
    results = []
    # Brave uses data-type="web" sections
    for match in re.finditer(
        r'<a[^>]*class="[^"]*result-header[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
        r'<p[^>]*class="[^"]*snippet-description[^"]*"[^>]*>(.*?)</p>',
        html, re.DOTALL
    ):
        url, title, snippet = match.group(1), match.group(2), match.group(3)
        title = re.sub(r"<[^>]+>", "", title).strip()
        snippet = re.sub(r"<[^>]+>", "", snippet).strip()
        if url.startswith("http") and title:
            results.append({"title": title, "url": url, "snippet": snippet})
    return results[:8]


def _parse_bing_html(html: str) -> list[dict]:
    results = []
    # Bing uses <li class="b_algo"> blocks
    for block in re.finditer(r'<li class="b_algo">(.*?)</li>', html, re.DOTALL):
        content = block.group(1)
        link = re.search(r'<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>', content, re.DOTALL)
        snippet_match = re.search(r'<p[^>]*>(.*?)</p>', content, re.DOTALL)
        if link:
            url = link.group(1)
            title = re.sub(r"<[^>]+>", "", link.group(2)).strip()
            snippet = re.sub(r"<[^>]+>", "", snippet_match.group(1)).strip() if snippet_match else ""
            results.append({"title": title, "url": url, "snippet": snippet})
    return results[:8]


def _parse_google_html(html: str) -> list[dict]:
    results = []
    # Google uses <div class="g"> blocks (simplified extraction)
    for block in re.finditer(r'<div class="g">(.*?)</div>\s*</div>\s*</div>', html, re.DOTALL):
        content = block.group(1)
        link = re.search(r'<a[^>]*href="(https?://[^"]*)"[^>]*>(.*?)</a>', content, re.DOTALL)
        if link:
            url = link.group(1)
            title = re.sub(r"<[^>]+>", "", link.group(2)).strip()
            # Try to find snippet
            snippet = ""
            span_match = re.search(r'<span[^>]*class="[^"]*"[^>]*>(.*?)</span>', content[content.find(url):], re.DOTALL)
            if span_match:
                snippet = re.sub(r"<[^>]+>", "", span_match.group(1)).strip()
            if title and not url.startswith("https://accounts.google"):
                results.append({"title": title, "url": url, "snippet": snippet})
    return results[:8]


# ── Deduplication + ranking ──────────────────────────────────────────────────

def _deduplicate_and_rank(results: list[dict]) -> list[dict]:
    """Deduplicate by URL domain+path, rank by cross-engine agreement."""
    from urllib.parse import urlparse

    seen: dict[str, dict] = {}  # normalized_url → merged result
    for r in results:
        try:
            parsed = urlparse(r.get("url", ""))
            key = f"{parsed.netloc}{parsed.path}".lower().rstrip("/")
        except Exception:
            key = r.get("url", "")

        if key in seen:
            seen[key]["found_in"].append(r.get("engine", "?"))
            # Keep longer snippet
            if len(r.get("snippet", "")) > len(seen[key].get("snippet", "")):
                seen[key]["snippet"] = r["snippet"]
        else:
            seen[key] = {**r, "found_in": [r.get("engine", "?")]}

    # Sort by: number of engines that found it (desc), then position
    ranked = sorted(seen.values(), key=lambda x: len(x.get("found_in", [])), reverse=True)
    return ranked
