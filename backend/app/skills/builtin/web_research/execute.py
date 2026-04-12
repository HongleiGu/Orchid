from __future__ import annotations


async def execute(query: str, max_sources: int = 5) -> str:
    """Search the web and return a plain-text summary of top results."""
    from app.tools.registry import tool_registry

    try:
        search = tool_registry.get("@orchid/web_search")
    except KeyError:
        return "@orchid/web_search tool is not registered."

    return await search.call(query=query, max_results=max_sources)
