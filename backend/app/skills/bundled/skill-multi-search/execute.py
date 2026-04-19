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
    engine_names: list[str] = []
    if "tavily" in active:
        tasks.append(_search_tavily(query, max_results, time_filter))
        engine_names.append("tavily")
    if "duckduckgo" in active:
        tasks.append(_search_duckduckgo(query))
        engine_names.append("duckduckgo")

    outcomes = await asyncio.gather(*tasks, return_exceptions=True)

    all_results: list[dict] = []
    engine_errors: list[str] = []
    for name, outcome in zip(engine_names, outcomes):
        if isinstance(outcome, Exception):
            engine_errors.append(f"{name}: unhandled {type(outcome).__name__}: {outcome}")
            logger.warning("Engine %s unhandled exception: %s", name, outcome)
            continue
        results, err = outcome
        if err:
            engine_errors.append(f"{name}: {err}")
        for r in results:
            r["engine"] = name
        all_results.extend(results)

    if not all_results:
        # Surface WHY we got nothing so the agent (and the user) can act on it.
        # Previously the skill claimed "No results found" on every failure mode,
        # which made the agent retry with variations forever.
        if engine_errors:
            return (
                f"[multi-search] No results for {query!r}. "
                f"All engines failed: {'; '.join(engine_errors)}. "
                f"Do not retry — fix the config or move on."
            )
        return (
            f"No results found for: {query}. "
            f"Do NOT retry this with rephrasing — 0 results from the search API "
            f"means 0 results. Either try a semantically different query or "
            f"proceed with what you have."
        )

    unique = _deduplicate(all_results)
    unique = unique[:max_results]

    lines = [f"**Web Search** — {len(unique)} results for \"{query}\":\n"]
    for i, r in enumerate(unique, 1):
        lines.append(f"### {i}. {r['title']}")
        lines.append(f"**URL**: {r['url']}")
        if r.get("snippet"):
            lines.append(f"> {r['snippet'][:400]}")
        lines.append("")

    # Include soft-failure notes so the agent knows coverage was partial.
    if engine_errors:
        lines.append(f"_(note: {'; '.join(engine_errors)})_")

    return "\n".join(lines)


async def _search_tavily(query: str, max_results: int, time_filter: str) -> tuple[list[dict], str | None]:
    """Returns (results, error_message). error_message is None on success."""
    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return [], "TAVILY_API_KEY not set in skill-runner environment"

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
            if resp.status_code >= 400:
                # Surface the provider's own error text (truncated) for the agent.
                return [], f"HTTP {resp.status_code}: {resp.text[:200]}"
            data = resp.json()

        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in data.get("results", [])
        ]
        return results, None
    except httpx.TimeoutException:
        return [], f"timed out after {_TIMEOUT}s"
    except Exception as exc:
        logger.warning("Tavily search failed: %s", exc)
        return [], f"{type(exc).__name__}: {exc}"


async def _search_duckduckgo(query: str) -> tuple[list[dict], str | None]:
    """DuckDuckGo Instant Answer API.

    NOTE: this is NOT a general web search — it only returns structured
    responses for well-known entities. For most research queries it comes
    back empty. Kept as a cheap secondary signal, not a real fallback.
    """
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

        for r in data.get("Results", [])[:3]:
            if isinstance(r, dict) and r.get("FirstURL"):
                results.append({
                    "title": r.get("Text", "")[:100],
                    "url": r["FirstURL"],
                    "snippet": r.get("Text", ""),
                })

        return results, None
    except httpx.TimeoutException:
        return [], f"timed out after {_TIMEOUT}s"
    except Exception as exc:
        logger.warning("DuckDuckGo failed: %s", exc)
        return [], f"{type(exc).__name__}: {exc}"


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
