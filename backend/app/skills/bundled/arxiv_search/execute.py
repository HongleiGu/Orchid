"""arxiv_search — query arxiv's public Atom API."""
from __future__ import annotations

import asyncio
from email.utils import parsedate_to_datetime
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

_API = "https://export.arxiv.org/api/query"
_NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}

# arxiv asks clients to make no more than one request every three seconds.
# Multiple DAG nodes can fire this skill concurrently, so keep a single
# process-wide lane for arxiv and add a small cushion above the documented
# minimum. The in-memory cache also prevents LLM retry loops from repeating
# identical searches during one runner lifetime.
_MIN_INTERVAL = 3.5
_MAX_RETRIES = 4
_CACHE_TTL = 15 * 60
_request_lock = asyncio.Lock()
_last_request_time = 0.0
_cooldown_until = 0.0
_cache: dict[str, tuple[float, str]] = {}


def _user_agent() -> str:
    return os.environ.get("ARXIV_USER_AGENT", "Orchid/0.1 arxiv_search")


def _retry_after_seconds(value: str | None, fallback: float) -> float:
    if not value:
        return fallback
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        return max(0.0, (retry_at - datetime.now(timezone.utc)).total_seconds())
    except (TypeError, ValueError, OverflowError):
        return fallback


async def _throttled_get(url: str) -> httpx.Response:
    global _last_request_time, _cooldown_until

    now = time.monotonic()
    cached = _cache.get(url)
    if cached and now - cached[0] < _CACHE_TTL:
        logger.info("arxiv_search cache hit")
        return httpx.Response(200, text=cached[1], request=httpx.Request("GET", url))

    resp: httpx.Response | None = None
    for attempt in range(_MAX_RETRIES):
        async with _request_lock:
            now = time.monotonic()
            if now < _cooldown_until:
                await asyncio.sleep(_cooldown_until - now)

            elapsed = time.monotonic() - _last_request_time
            if elapsed < _MIN_INTERVAL:
                await asyncio.sleep(_MIN_INTERVAL - elapsed)
            _last_request_time = time.monotonic()

            async with httpx.AsyncClient(timeout=30, headers={"User-Agent": _user_agent()}) as client:
                resp = await client.get(url)

        if resp.status_code != 429:
            if resp.status_code == 200:
                _cache[url] = (time.monotonic(), resp.text)
            return resp

        wait = _retry_after_seconds(
            resp.headers.get("Retry-After"),
            fallback=min(60.0, _MIN_INTERVAL * (2 ** (attempt + 1))),
        )
        _cooldown_until = max(_cooldown_until, time.monotonic() + wait)
        logger.warning("arxiv_search got 429; backing off %.1fs (attempt %d/%d)", wait, attempt + 1, _MAX_RETRIES)
        await asyncio.sleep(wait)

    assert resp is not None
    return resp


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
        resp = await _throttled_get(f"{_API}?{urlencode(params)}")
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
