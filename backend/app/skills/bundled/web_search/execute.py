"""Multi-provider web/news search.

Provider order is Tavily -> Brave -> SerpAPI; the first provider with a
configured key that answers a query wins, and the rest are only used as
fallbacks. Nothing here fabricates results: if no provider is configured the
skill says so explicitly rather than returning an empty table that reads like
"there is no news".
"""
from __future__ import annotations

import asyncio
import os
from typing import Any
from urllib.parse import urlparse

import httpx

_TIMEOUT = 25
_MAX_RESULTS = 25
_SNIPPET_CHARS = 700

# Finance-leaning domains used when topic=finance and the caller gave no
# include_domains of their own. Mainland-accessible sources first.
_FINANCE_DOMAINS = [
    "eastmoney.com", "stcn.com", "cs.com.cn", "cnstock.com", "yicai.com",
    "wallstreetcn.com", "jin10.com", "10jqka.com.cn", "sina.com.cn",
    "caixin.com", "21jingji.com", "reuters.com", "cnbc.com", "marketwatch.com",
    "bloomberg.com", "ft.com", "investing.com", "scmp.com",
]


async def execute(
    query: str,
    queries: list[str] | None = None,
    topic: str = "news",
    days: int = 3,
    max_results: int = 10,
    include_domains: list[str] | None = None,
    exclude_domains: list[str] | None = None,
) -> str:
    all_queries = _unique(
        [str(query or "").strip()] + [str(q).strip() for q in (queries or [])]
    )
    if not all_queries:
        return "Error: query must be non-empty."

    limit = max(1, min(int(max_results or 10), _MAX_RESULTS))
    window = max(1, min(int(days or 3), 30))
    topic = (topic or "news").lower().strip()
    includes = [d.strip().lower() for d in (include_domains or []) if str(d).strip()]
    excludes = [d.strip().lower() for d in (exclude_domains or []) if str(d).strip()]
    if topic == "finance" and not includes:
        includes = list(_FINANCE_DOMAINS)

    providers = _available_providers()
    if not providers:
        return (
            "Error: no search provider is configured. Set one of TAVILY_API_KEY, "
            "BRAVE_API_KEY, or SERPAPI_API_KEY in the environment. "
            "No results were returned - do not treat this as 'no news found'."
        )

    notes: list[str] = []
    results: list[dict[str, Any]] = []
    used_provider = ""

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": "Orchid web_search/1.0"},
    ) as client:
        for provider in providers:
            batches = await asyncio.gather(
                *[
                    _search(client, provider, q, topic, window, limit, includes, excludes)
                    for q in all_queries
                ],
                return_exceptions=True,
            )
            got_any = False
            for q, batch in zip(all_queries, batches):
                if isinstance(batch, Exception):
                    notes.append(f"{provider} failed on {q!r}: {type(batch).__name__}: {batch}")
                    continue
                if not batch:
                    notes.append(f"{provider} returned 0 results for {q!r}.")
                    continue
                got_any = True
                for item in batch:
                    item["query"] = q
                results.extend(batch)
            if got_any:
                used_provider = provider
                break
            notes.append(f"Falling back from {provider}: no query returned results.")

    deduped = _dedupe(results, excludes)[:limit]
    if not deduped:
        return (
            "# Web search\n\n"
            f"Queries: {', '.join(all_queries)}\n\n"
            "**No results returned.** This is a provider/connectivity outcome, not "
            "evidence that nothing was published.\n\n## Diagnostics\n"
            + "\n".join(f"- {n}" for n in notes)
        )

    lines = ["# Web search results", ""]
    lines.append(
        f"Provider: **{used_provider}** | topic: `{topic}` | window: {window}d "
        f"| queries: {len(all_queries)} | unique results: {len(deduped)}"
    )
    lines.append("")
    lines.append("| # | Title | Source | Published | URL |")
    lines.append("|---|---|---|---|---|")
    for i, r in enumerate(deduped, 1):
        lines.append(
            f"| {i} | {_cell(r['title'])} | {_cell(r['domain'])} | "
            f"{_cell(r.get('published') or 'n/a')} | {r['url']} |"
        )
    lines.append("")
    lines.append("## Snippets")
    for i, r in enumerate(deduped, 1):
        lines.append(f"\n### {i}. {r['title']}")
        lines.append(
            f"{r['url']}  -  {r['domain']}  -  {r.get('published') or 'date n/a'}"
            f"  -  matched query: {r.get('query', '')}"
        )
        snippet = (r.get("snippet") or "").strip()
        lines.append(snippet[:_SNIPPET_CHARS] if snippet else "_no snippet returned_")
    if notes:
        lines.append("\n## Coverage notes")
        lines.extend(f"- {n}" for n in notes)
    return "\n".join(lines)


# -- providers ---------------------------------------------------------------

def _available_providers() -> list[str]:
    order = []
    if os.environ.get("TAVILY_API_KEY"):
        order.append("tavily")
    if os.environ.get("BRAVE_API_KEY"):
        order.append("brave")
    if os.environ.get("SERPAPI_API_KEY"):
        order.append("serpapi")
    preferred = (os.environ.get("SEARCH_PROVIDER") or "").strip().lower()
    if preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)
    return order


async def _search(
    client: httpx.AsyncClient,
    provider: str,
    query: str,
    topic: str,
    days: int,
    limit: int,
    includes: list[str],
    excludes: list[str],
) -> list[dict[str, Any]]:
    if provider == "tavily":
        return await _tavily(client, query, topic, days, limit, includes, excludes)
    if provider == "brave":
        return await _brave(client, query, topic, limit)
    if provider == "serpapi":
        return await _serpapi(client, query, topic, limit)
    return []


async def _tavily(client, query, topic, days, limit, includes, excludes):
    payload: dict[str, Any] = {
        "api_key": os.environ["TAVILY_API_KEY"],
        "query": query,
        "max_results": min(limit * 2, 20),
        "search_depth": "advanced",
        "include_answer": False,
        "topic": "news" if topic in ("news", "finance") else "general",
    }
    if topic in ("news", "finance"):
        payload["days"] = days
    if includes:
        payload["include_domains"] = includes[:50]
    if excludes:
        payload["exclude_domains"] = excludes[:50]
    resp = await client.post("https://api.tavily.com/search", json=payload)
    resp.raise_for_status()
    data = resp.json()
    return [
        _norm(
            title=r.get("title"),
            url=r.get("url"),
            snippet=r.get("content"),
            published=r.get("published_date"),
        )
        for r in (data.get("results") or [])
        if r.get("url")
    ]


async def _brave(client, query, topic, limit):
    news = topic in ("news", "finance")
    url = (
        "https://api.search.brave.com/res/v1/news/search"
        if news
        else "https://api.search.brave.com/res/v1/web/search"
    )
    resp = await client.get(
        url,
        params={"q": query, "count": min(limit * 2, 20)},
        headers={
            "X-Subscription-Token": os.environ["BRAVE_API_KEY"],
            "Accept": "application/json",
        },
    )
    resp.raise_for_status()
    data = resp.json()
    raw = (data.get("results") if news else (data.get("web") or {}).get("results")) or []
    return [
        _norm(
            title=r.get("title"),
            url=r.get("url"),
            snippet=r.get("description"),
            published=r.get("age") or r.get("page_age"),
        )
        for r in raw
        if r.get("url")
    ]


async def _serpapi(client, query, topic, limit):
    params = {
        "q": query,
        "api_key": os.environ["SERPAPI_API_KEY"],
        "num": min(limit * 2, 20),
        "engine": "google",
    }
    if topic in ("news", "finance"):
        params["tbm"] = "nws"
    resp = await client.get("https://serpapi.com/search.json", params=params)
    resp.raise_for_status()
    data = resp.json()
    raw = data.get("news_results") or data.get("organic_results") or []
    return [
        _norm(
            title=r.get("title"),
            url=r.get("link"),
            snippet=r.get("snippet"),
            published=r.get("date"),
        )
        for r in raw
        if r.get("link")
    ]


# -- helpers -----------------------------------------------------------------

def _norm(title, url, snippet, published) -> dict[str, Any]:
    url = str(url or "").strip()
    return {
        "title": (str(title or "").strip() or url) or "(untitled)",
        "url": url,
        "snippet": str(snippet or "").strip(),
        "published": str(published or "").strip(),
        "domain": _domain(url),
    }


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
        return host[4:] if host.startswith("www.") else host
    except ValueError:
        return ""


def _dedupe(items: list[dict], excludes: list[str]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for item in items:
        url = item.get("url") or ""
        key = url.split("#")[0].split("?")[0].rstrip("/").lower()
        if not key or key in seen:
            continue
        domain = item.get("domain", "")
        if any(domain == e or domain.endswith("." + e) for e in excludes):
            continue
        seen.add(key)
        out.append(item)
    return out


def _unique(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v and v not in seen:
            seen.add(v)
            out.append(v)
    return out


def _cell(text: str) -> str:
    return str(text or "").replace("|", "/").replace("\n", " ").strip()[:160]
