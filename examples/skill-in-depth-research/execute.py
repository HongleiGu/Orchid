"""
In-depth research skill — iterative multi-step web research.

Searches using Tavily API (primary) with Semantic Scholar as academic fallback.
"""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)

DEPTH_SEARCHES = {"overview": 2, "thorough": 4, "exhaustive": 8}


async def execute(
    topic: str,
    depth: str = "thorough",
    max_searches: int = 4,
) -> str:
    max_searches = min(max_searches, DEPTH_SEARCHES.get(depth, 4))

    findings: list[dict] = []

    # Round 1: Academic search (Semantic Scholar — free, no key needed)
    academic = await _search_semantic_scholar(topic, limit=5)
    for r in academic:
        findings.append({**r, "round": 1, "query": topic})

    # Rounds 2+: Web search via Tavily (if key set) for broader context
    queries = _generate_queries(topic, max_searches - 1)
    for i, query in enumerate(queries, start=2):
        logger.info("Research search %d: %s", i, query)
        results = await _search_tavily(query)
        for r in results:
            findings.append({**r, "round": i, "query": query})

    if not findings:
        return f"Could not find substantive information on: {topic}"

    return _build_report(topic, depth, findings)


async def _search_semantic_scholar(query: str, limit: int = 5) -> list[dict]:
    """Search Semantic Scholar API — free, no key, good for academic papers."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                "https://api.semanticscholar.org/graph/v1/paper/search",
                params={
                    "query": query,
                    "limit": limit,
                    "fields": "title,abstract,url,authors,year,citationCount",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        results = []
        for paper in data.get("data", []):
            authors = ", ".join(a.get("name", "") for a in (paper.get("authors") or [])[:3])
            abstract = paper.get("abstract") or ""
            results.append({
                "title": paper.get("title", ""),
                "url": paper.get("url", ""),
                "content": f"({paper.get('year', '?')}, {paper.get('citationCount', 0)} citations) {abstract[:400]}",
                "source": "Semantic Scholar",
            })
        return results

    except Exception as exc:
        logger.warning("Semantic Scholar search failed: %s", exc)
        return []


async def _search_tavily(query: str, max_results: int = 3) -> list[dict]:
    """Search using Tavily API."""
    import httpx

    api_key = os.environ.get("TAVILY_API_KEY", "")
    if not api_key:
        return await _search_duckduckgo(query)

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": api_key,
                    "query": query,
                    "max_results": max_results,
                    "search_depth": "advanced",
                    "include_answer": False,
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "content": r.get("content", ""),
                "source": "Tavily",
            }
            for r in data.get("results", [])
        ]
    except Exception as exc:
        logger.warning("Tavily search failed: %s", exc)
        return await _search_duckduckgo(query)


async def _search_duckduckgo(query: str) -> list[dict]:
    """Fallback: DuckDuckGo Instant Answer API (JSON, no scraping)."""
    import httpx

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                "https://api.duckduckgo.com/",
                params={"q": query, "format": "json", "no_html": 1},
                headers={"User-Agent": "OrchidResearch/1.0"},
            )
            data = resp.json()

        results = []
        # Abstract
        if data.get("Abstract"):
            results.append({
                "title": data.get("Heading", query),
                "url": data.get("AbstractURL", ""),
                "content": data["Abstract"],
                "source": "DuckDuckGo",
            })
        # Related topics
        for topic in data.get("RelatedTopics", [])[:3]:
            if isinstance(topic, dict) and topic.get("Text"):
                results.append({
                    "title": topic.get("Text", "")[:80],
                    "url": topic.get("FirstURL", ""),
                    "content": topic.get("Text", ""),
                    "source": "DuckDuckGo",
                })
        return results

    except Exception as exc:
        logger.warning("DuckDuckGo fallback failed: %s", exc)
        return []


def _generate_queries(topic: str, count: int) -> list[str]:
    refinements = [
        f"{topic} latest research 2025 2026",
        f"{topic} technical approach method",
        f"{topic} results benchmarks comparison",
        f"{topic} limitations future work",
    ]
    return refinements[:count]


def _build_report(topic: str, depth: str, findings: list[dict]) -> str:
    # Deduplicate by URL
    seen_urls: set[str] = set()
    unique: list[dict] = []
    for f in findings:
        url = f.get("url", "")
        if url and url in seen_urls:
            continue
        if url:
            seen_urls.add(url)
        unique.append(f)

    # Group by round
    rounds: dict[int, list[dict]] = {}
    for f in unique:
        rounds.setdefault(f["round"], []).append(f)

    lines = [
        f"# Research Report: {topic}",
        f"**Depth**: {depth} | **Sources**: {len(unique)}",
        "",
    ]

    for round_num in sorted(rounds.keys()):
        round_findings = rounds[round_num]
        query = round_findings[0]["query"]
        source_type = round_findings[0].get("source", "Web")
        lines.append(f"### Round {round_num} ({source_type}): \"{query}\"")
        lines.append("")
        for f in round_findings:
            title = f.get("title", "Untitled")
            content = f.get("content", "")
            if len(content) > 300:
                content = content[:300] + "..."
            url = f.get("url", "")
            if url:
                lines.append(f"- **[{title}]({url})**: {content}")
            else:
                lines.append(f"- **{title}**: {content}")
        lines.append("")

    # Sources list
    sources = [f for f in unique if f.get("url")]
    if sources:
        lines.append("## Sources")
        lines.append("")
        for i, s in enumerate(sources[:15], 1):
            lines.append(f"{i}. [{s['title']}]({s['url']})")

    return "\n".join(lines)
