from __future__ import annotations

from app.tools.base import BaseTool


class WebSearchTool(BaseTool):
    name = "@orchid/web_search"
    description = "Search the web for up-to-date information."
    parameters = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "The search query."},
            "max_results": {
                "type": "integer",
                "default": 5,
                "description": "Maximum number of results to return.",
            },
        },
        "required": ["query"],
    }

    async def call(self, query: str, max_results: int = 5) -> str:
        from app.config import get_settings

        settings = get_settings()
        provider = settings.search_provider.lower()

        if provider == "tavily":
            return await self._tavily(query, max_results, settings.tavily_api_key)
        if provider == "brave":
            return await self._brave(query, max_results, settings.brave_api_key)
        return f"Search provider {provider!r} is not configured."

    async def _tavily(self, query: str, max_results: int, api_key: str) -> str:
        if not api_key:
            return "Error: TAVILY_API_KEY is not set."
        from tavily import AsyncTavilyClient  # lazy import

        client = AsyncTavilyClient(api_key=api_key)
        resp = await client.search(query, max_results=max_results)
        items = resp.get("results", [])
        return "\n\n".join(
            f"**{r['title']}**\n{r['url']}\n{r.get('content', '')}" for r in items
        )

    async def _brave(self, query: str, max_results: int, api_key: str) -> str:
        if not api_key:
            return "Error: BRAVE_API_KEY is not set."
        import httpx

        url = "https://api.search.brave.com/res/v1/web/search"
        headers = {"Accept": "application/json", "X-Subscription-Token": api_key}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, params={"q": query, "count": max_results}, headers=headers)
            data = resp.json()
        results = data.get("web", {}).get("results", [])
        return "\n\n".join(
            f"**{r['title']}**\n{r['url']}\n{r.get('description', '')}" for r in results
        )
