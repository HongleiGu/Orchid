"""
Multi-source web search — uses APIs instead of HTML scraping.

Primary: Tavily API (if key set) — reliable, returns snippets
Fallback: DuckDuckGo JSON API — limited but no key needed
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 12
ALL_ENGINES = ["tavily", "duckduckgo"]


async def execute(
    query: str,
    engines: str = "all",
    max_results: int = 10,
    time_filter: str = "any",
) -> str:
    active = set(ALL_ENGINES) if engines.strip().lower() == "all" else {
        e.strip().lower() for e in engines.split(",") if e.strip()
    }

    tasks = []
    if "tavily" in active:
        tasks.append(_search_tavily(query, max_results, time_filter))
    if "duckduckgo" in active:
        tasks.append(_search_duckduckgo(query))

    results_lists = await asyncio.gather(*tasks, return_exceptions=True)

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
        return f"No results found for: {query}"

    unique = _deduplicate(all_results)
    unique = unique[:max_results]

    lines = [f"**Web Search** — {len(unique)} results for \"{query}\":\n"]
    for i, r in enumerate(unique, 1):
        lines.append(f"### {i}. {r['title']}")
        lines.append(f"**URL**: {r['url']}")
        if r.get("snippet"):
            lines.append(f"> {r['snippet'][:400]}")
        lines.append("")

    return "\n".join(lines)


async def _search_tavily(query: str, max_results: int, time_filter: str) -> list[dict]:
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return []

    body: dict = {
        "api_key": api_key,
        "query": query,
        "max_results": min(max_results, 10),
        "search_depth": "advanced",
        "include_answer": False,
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post("https://api.tavily.com/search", json=body)
            resp.raise_for_status()
            data = resp.json()

        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in data.get("results", [])
        ]
    except Exception as exc:
        logger.warning("Tavily search failed: %s", exc)
        return []


async def _search_duckduckgo(query: str) -> list[dict]:
    """DuckDuckGo JSON Instant Answer API — limited but reliable."""
    results: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
            )
            data = resp.json()

        if data.get("AbstractURL") and data.get("Abstract"):
            results.append({
                "title": data.get("Heading", query),
                "url": data["AbstractURL"],
                "snippet": data["Abstract"],
            })

        for topic in data.get("RelatedTopics", [])[:5]:
            if isinstance(topic, dict) and topic.get("FirstURL") and topic.get("Text"):
                results.append({
                    "title": topic["Text"][:100],
                    "url": topic["FirstURL"],
                    "snippet": topic["Text"],
                })

        # Also try Results section
        for r in data.get("Results", [])[:3]:
            if isinstance(r, dict) and r.get("FirstURL"):
                results.append({
                    "title": r.get("Text", "")[:100],
                    "url": r["FirstURL"],
                    "snippet": r.get("Text", ""),
                })

    except Exception as exc:
        logger.warning("DuckDuckGo failed: %s", exc)

    return results


def _deduplicate(results: list[dict]) -> list[dict]:
    from urllib.parse import urlparse

    seen: dict[str, dict] = {}
    for r in results:
        try:
            parsed = urlparse(r.get("url", ""))
            key = f"{parsed.netloc}{parsed.path}".lower().rstrip("/")
        except Exception:
            key = r.get("url", "")
        if not key:
            continue
        if key not in seen:
            seen[key] = r
        elif len(r.get("snippet", "")) > len(seen[key].get("snippet", "")):
            seen[key]["snippet"] = r["snippet"]
    return list(seen.values())
