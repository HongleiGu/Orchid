from __future__ import annotations

import os

import httpx


async def execute(query: str, max_results: int = 5) -> str:
    provider = os.environ.get("SEARCH_PROVIDER", "tavily").lower()

    if provider == "tavily":
        return await _tavily(query, max_results, os.environ.get("TAVILY_API_KEY", ""))
    if provider == "brave":
        return await _brave(query, max_results, os.environ.get("BRAVE_API_KEY", ""))
    return f"Search provider {provider!r} is not configured."


async def _tavily(query: str, max_results: int, api_key: str) -> str:
    if not api_key:
        return "Error: TAVILY_API_KEY is not set."
    from tavily import AsyncTavilyClient

    client = AsyncTavilyClient(api_key=api_key)
    resp = await client.search(query, max_results=max_results)
    items = resp.get("results", [])
    return "\n\n".join(
        f"**{r['title']}**\n{r['url']}\n{r.get('content', '')}" for r in items
    )


async def _brave(query: str, max_results: int, api_key: str) -> str:
    if not api_key:
        return "Error: BRAVE_API_KEY is not set."

    url = "https://api.search.brave.com/res/v1/web/search"
    headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params={"q": query, "count": max_results}, headers=headers)
        data = resp.json()
    results = data.get("web", {}).get("results", [])
    return "\n\n".join(
        f"**{r['title']}**\n{r['url']}\n{r.get('description', '')}" for r in results
    )
