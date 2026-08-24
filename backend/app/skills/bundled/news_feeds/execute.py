"""Primary-source news aggregation.

Two kinds of source are supported: plain RSS/Atom (parsed with the stdlib XML
parser) and Chinese realtime flash wires, which are JSON/JSONP endpoints that
each need their own small adapter. Every source carries a `cn_ok` flag stating
whether it resolves from mainland China without a proxy, because that is the
difference between "no news" and "you cannot see the news from here".
"""
from __future__ import annotations

import asyncio
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from calendar import timegm
from email.utils import parsedate_tz
from typing import Any

import httpx

_TIMEOUT = 20
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
_SUMMARY_CHARS = 260
_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")

# name, kind, url, cn_ok, note
_SOURCES: dict[str, list[dict[str, Any]]] = {
    "cn_flash": [
        {
            "name": "华尔街见闻 7x24 快讯",
            "kind": "wscn_lives",
            "url": "https://api.wallstreetcn.com/apiv1/content/lives?channel=global-channel&limit=40",
            "cn_ok": True,
        },
        {
            "name": "新浪财经 7x24 直播",
            "kind": "sina_zhibo",
            "url": "https://zhibo.sina.com.cn/api/zhibo/feed?page=1&page_size=40&zhibo_id=152&tag_id=0",
            "cn_ok": True,
        },
        {
            "name": "金十数据 快讯",
            "kind": "jin10",
            "url": "https://flash-api.jin10.com/get_flash_list?channel=-8200&vip=1",
            "cn_ok": True,
        },
        {
            "name": "东方财富 快讯",
            "kind": "eastmoney_kuaixun",
            "url": "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html",
            "cn_ok": True,
        },
    ],
    "cn_finance": [
        {
            "name": "新浪财经 滚动新闻",
            "kind": "sina_roll",
            "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=155&lid=1686&num=40&page=1",
            "cn_ok": True,
        },
        {
            "name": "新浪财经 证券/股市",
            "kind": "sina_roll",
            "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&num=40&page=1",
            "cn_ok": True,
        },
        {
            "name": "新浪财经 宏观经济",
            "kind": "sina_roll",
            "url": "https://feed.mix.sina.com.cn/api/roll/get?pageid=155&lid=1690&num=30&page=1",
            "cn_ok": True,
        },
        {
            "name": "华尔街见闻 资讯",
            "kind": "wscn_articles",
            "url": "https://api.wallstreetcn.com/apiv1/content/articles?limit=30",
            "cn_ok": True,
        },
    ],
    "global_markets": [
        # Two Chinese-language wires that cover overseas markets, so this bundle
        # still returns something when cn_accessible_only drops the rest.
        {
            "name": "华尔街见闻 全球快讯",
            "kind": "wscn_lives",
            "url": "https://api.wallstreetcn.com/apiv1/content/lives?channel=global-channel&limit=40",
            "cn_ok": True,
        },
        {
            "name": "东方财富 全球快讯",
            "kind": "eastmoney_kuaixun",
            "url": "https://newsapi.eastmoney.com/kuaixun/v1/getlist_102_ajaxResult_50_1_.html",
            "cn_ok": True,
        },
        {
            "name": "CNBC Markets",
            "kind": "rss",
            "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=20910258",
            "cn_ok": False,
        },
        {
            "name": "CNBC Top News",
            "kind": "rss",
            "url": "https://search.cnbc.com/rs/search/combinedcms/view.xml?partnerId=wrss01&id=100003114",
            "cn_ok": False,
        },
        {
            "name": "MarketWatch Top Stories",
            "kind": "rss",
            "url": "https://feeds.content.dowjones.io/public/rss/mw_topstories",
            "cn_ok": False,
        },
        {
            "name": "Yahoo Finance",
            "kind": "rss",
            "url": "https://finance.yahoo.com/news/rssindex",
            "cn_ok": False,
        },
        {
            "name": "Investing.com News",
            "kind": "rss",
            "url": "https://www.investing.com/rss/news.rss",
            "cn_ok": False,
        },
        {
            "name": "SCMP Business",
            "kind": "rss",
            "url": "https://www.scmp.com/rss/92/feed",
            "cn_ok": False,
        },
    ],
    "global_macro": [
        {
            "name": "US Federal Reserve press releases",
            "kind": "rss",
            "url": "https://www.federalreserve.gov/feeds/press_all.xml",
            "cn_ok": False,
        },
        {
            "name": "ECB press releases",
            "kind": "rss",
            "url": "https://www.ecb.europa.eu/rss/press.html",
            "cn_ok": False,
        },
        {
            "name": "FT Home",
            "kind": "rss",
            "url": "https://www.ft.com/rss/home",
            "cn_ok": False,
        },
        {
            "name": "Investing.com Economic News",
            "kind": "rss",
            "url": "https://www.investing.com/rss/news_14.rss",
            "cn_ok": False,
        },
    ],
}

_JIN10_HEADERS = {
    "x-app-id": "bVBF4FyRTn5NJF5n",
    "x-version": "1.0.0",
    "Referer": "https://www.jin10.com/",
}


async def execute(
    bundle: str = "cn_flash",
    limit: int = 40,
    hours: int = 24,
    keywords: list[str] | None = None,
    extra_feeds: list[str] | None = None,
    cn_accessible_only: bool = False,
) -> str:
    bundle = (bundle or "cn_flash").strip().lower()
    if bundle == "all":
        sources = [s for group in _SOURCES.values() for s in group]
    elif bundle in _SOURCES:
        sources = list(_SOURCES[bundle])
    else:
        return f"Error: unknown bundle {bundle!r}. Choose from: {', '.join(_SOURCES)}, all."

    for url in extra_feeds or []:
        clean = str(url).strip()
        if clean:
            sources.append({"name": clean, "kind": "rss", "url": clean, "cn_ok": None})

    skipped = []
    if cn_accessible_only:
        skipped = [s["name"] for s in sources if s.get("cn_ok") is False]
        sources = [s for s in sources if s.get("cn_ok") is not False]

    cap = max(5, min(int(limit or 40), 150))
    window = max(1, min(int(hours or 24), 168)) * 3600
    terms = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    now = time.time()

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"},
    ) as client:
        fetched = await asyncio.gather(
            *[_fetch_source(client, s) for s in sources], return_exceptions=True
        )

    items: list[dict[str, Any]] = []
    diagnostics: list[str] = []
    for source, result in zip(sources, fetched):
        if isinstance(result, Exception):
            diagnostics.append(
                f"- FAILED **{source['name']}** ({_reach(source)}): "
                f"{type(result).__name__}: {result}"
            )
            continue
        if not result:
            diagnostics.append(f"- EMPTY **{source['name']}** ({_reach(source)}): 0 items parsed.")
            continue
        diagnostics.append(f"- ok **{source['name']}** ({_reach(source)}): {len(result)} items.")
        items.extend(result)

    fresh = []
    undated = 0
    for item in items:
        ts = item.get("ts")
        if ts and now - ts > window:
            continue
        if not ts:
            undated += 1
        if terms and not any(t in item["title"] or t in item.get("summary", "") for t in terms):
            continue
        fresh.append(item)

    fresh = _dedupe(fresh)
    fresh.sort(key=lambda i: i.get("ts") or 0, reverse=True)
    fresh = fresh[:cap]

    if not fresh:
        reason = (
            "every source in this bundle was skipped as unreachable from mainland China"
            if skipped and not sources
            else "no source returned an item inside the window"
        )
        tail = list(diagnostics)
        if skipped:
            tail.append(
                "- Skipped as not reachable from mainland China without a proxy: "
                + ", ".join(skipped)
            )
        return (
            f"# News feed ({bundle})\n\n**No items returned** within the last "
            f"{hours}h - {reason}. Treat this as a fetch/connectivity result, not "
            f"as an absence of news.\n\n## Source diagnostics\n" + "\n".join(tail)
        )

    lines = [
        f"# News feed - bundle `{bundle}`",
        "",
        f"{len(fresh)} headlines from {len({i['source'] for i in fresh})} sources, "
        f"window {hours}h, generated {_fmt(now)} UTC."
        + (f" Keyword filter: {', '.join(terms)}." if terms else ""),
        "",
        "| Time (UTC) | Source | Headline | URL |",
        "|---|---|---|---|",
    ]
    for item in fresh:
        stamp = _fmt(item["ts"]) if item.get("ts") else "undated"
        lines.append(
            f"| {stamp} | {_cell(item['source'])} | {_cell(item['title'])} | "
            f"{item.get('url') or '-'} |"
        )

    detailed = [i for i in fresh if i.get("summary")][:25]
    if detailed:
        lines.append("\n## Details")
        for item in detailed:
            stamp = _fmt(item["ts"]) if item.get("ts") else "undated"
            lines.append(f"\n**[{stamp}] {item['source']} - {item['title']}**")
            if item.get("url"):
                lines.append(item["url"])
            lines.append(item["summary"][:_SUMMARY_CHARS])

    lines.append("\n## Source diagnostics")
    lines.extend(diagnostics)
    if undated:
        lines.append(f"- {undated} item(s) had no parseable timestamp and were kept unfiltered.")
    if skipped:
        lines.append(
            "- Skipped as not reachable from mainland China without a proxy: "
            + ", ".join(skipped)
        )
    return "\n".join(lines)


# -- fetching ----------------------------------------------------------------

async def _fetch_source(client: httpx.AsyncClient, source: dict) -> list[dict]:
    kind = source["kind"]
    headers = _JIN10_HEADERS if kind == "jin10" else {}
    resp = await client.get(source["url"], headers=headers)
    resp.raise_for_status()
    parser = _PARSERS[kind]
    return parser(resp, source["name"])


def _parse_rss(resp: httpx.Response, name: str) -> list[dict]:
    try:
        root = ET.fromstring(_sanitize_xml(resp.content))
    except ET.ParseError:
        # Some publishers emit XML that is not well-formed (unescaped
        # ampersands, stray tags inside CDATA). Salvage the item blocks by hand
        # rather than losing the whole feed.
        return _salvage_rss(resp.text, name)
    out: list[dict] = []
    # RSS 2.0
    for node in root.iter("item"):
        out.append(
            {
                "source": name,
                "title": _text(_find(node, "title")),
                "summary": _text(_find(node, "description")),
                "url": (_find(node, "link") or "").strip(),
                "ts": _rfc822(_find(node, "pubDate") or _find(node, "date")),
            }
        )
    if out:
        return [i for i in out if i["title"]]
    # Atom
    ns = "{http://www.w3.org/2005/Atom}"
    for node in root.iter(f"{ns}entry"):
        link = ""
        for link_node in node.findall(f"{ns}link"):
            if link_node.get("rel") in (None, "alternate"):
                link = link_node.get("href") or ""
                break
        out.append(
            {
                "source": name,
                "title": _text(_findtext(node, f"{ns}title")),
                "summary": _text(
                    _findtext(node, f"{ns}summary") or _findtext(node, f"{ns}content")
                ),
                "url": link,
                "ts": _iso(_findtext(node, f"{ns}updated") or _findtext(node, f"{ns}published")),
            }
        )
    return [i for i in out if i["title"]]


_XML_BAD_CHARS = re.compile(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ITEM_BLOCK = re.compile(r"<item[^>]*>(.*?)</item>", re.IGNORECASE | re.DOTALL)


def _sanitize_xml(raw: bytes) -> bytes:
    return _XML_BAD_CHARS.sub(b" ", raw)


def _salvage_rss(text: str, name: str) -> list[dict]:
    out = []
    for block in _ITEM_BLOCK.findall(text):
        title = _text(_first_tag(block, "title"))
        if not title:
            continue
        out.append(
            {
                "source": name,
                "title": title,
                "summary": _text(_first_tag(block, "description")),
                "url": _text(_first_tag(block, "link")),
                "ts": _rfc822(_text(_first_tag(block, "pubDate"))),
            }
        )
    return out


def _first_tag(block: str, tag: str) -> str:
    match = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", block, re.IGNORECASE | re.DOTALL)
    if not match:
        return ""
    value = match.group(1)
    cdata = re.match(r"\s*<!\[CDATA\[(.*?)\]\]>\s*$", value, re.DOTALL)
    return cdata.group(1) if cdata else value


def _parse_wscn_lives(resp: httpx.Response, name: str) -> list[dict]:
    data = resp.json().get("data") or {}
    out = []
    for item in data.get("items") or []:
        title = _text(item.get("title") or item.get("content_text") or "")
        if not title:
            continue
        out.append(
            {
                "source": name,
                "title": title[:180],
                "summary": _text(item.get("content_text") or ""),
                "url": item.get("uri") or "",
                "ts": _epoch(item.get("display_time")),
            }
        )
    return out


def _parse_wscn_articles(resp: httpx.Response, name: str) -> list[dict]:
    data = resp.json().get("data") or {}
    out = []
    for item in data.get("items") or []:
        resource = item.get("resource") or item
        title = _text(resource.get("title") or "")
        if not title:
            continue
        out.append(
            {
                "source": name,
                "title": title,
                "summary": _text(resource.get("content_short") or ""),
                "url": resource.get("uri") or "",
                "ts": _epoch(resource.get("display_time")),
            }
        )
    return out


def _parse_sina_zhibo(resp: httpx.Response, name: str) -> list[dict]:
    result = resp.json().get("result") or {}
    feed = (result.get("data") or {}).get("feed") or {}
    out = []
    for item in feed.get("list") or []:
        title = _text(item.get("rich_text") or item.get("text") or "")
        if not title:
            continue
        out.append(
            {
                "source": name,
                "title": title[:180],
                "summary": title,
                "url": (item.get("docurl") or "").strip(),
                "ts": _epoch(item.get("create_time")),
            }
        )
    return out


def _parse_sina_roll(resp: httpx.Response, name: str) -> list[dict]:
    result = resp.json().get("result") or {}
    out = []
    for item in result.get("data") or []:
        title = _text(item.get("title") or "")
        if not title:
            continue
        out.append(
            {
                "source": name,
                "title": title,
                "summary": _text(item.get("intro") or ""),
                "url": item.get("url") or "",
                "ts": _epoch(item.get("ctime")),
            }
        )
    return out


def _parse_jin10(resp: httpx.Response, name: str) -> list[dict]:
    payload = resp.json()
    out = []
    for item in payload.get("data") or []:
        body = item.get("data") or {}
        title = _text(body.get("title") or body.get("content") or "")
        if not title:
            continue
        out.append(
            {
                "source": name,
                "title": title[:180],
                "summary": _text(body.get("content") or ""),
                "url": (body.get("link") or "").strip(),
                "ts": _epoch(item.get("time")),
            }
        )
    return out


def _parse_eastmoney_kuaixun(resp: httpx.Response, name: str) -> list[dict]:
    # JSONP: `var ajaxResult={...};`
    text = resp.text
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return []
    payload = json.loads(text[start : end + 1])
    out = []
    for item in payload.get("LivesList") or []:
        title = _text(item.get("title") or "")
        if not title:
            continue
        out.append(
            {
                "source": name,
                "title": title,
                "summary": _text(item.get("digest") or ""),
                "url": item.get("url_w") or item.get("url_unique") or "",
                "ts": _epoch(item.get("showtime")),
            }
        )
    return out


_PARSERS = {
    "rss": _parse_rss,
    "wscn_lives": _parse_wscn_lives,
    "wscn_articles": _parse_wscn_articles,
    "sina_zhibo": _parse_sina_zhibo,
    "sina_roll": _parse_sina_roll,
    "jin10": _parse_jin10,
    "eastmoney_kuaixun": _parse_eastmoney_kuaixun,
}


# -- helpers -----------------------------------------------------------------

def _find(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    if child is not None and child.text:
        return child.text
    # Namespaced fallback (e.g. dc:date, content:encoded).
    for sub in node:
        if sub.tag.rsplit("}", 1)[-1] == tag and sub.text:
            return sub.text
    return ""


def _findtext(node: ET.Element, tag: str) -> str:
    child = node.find(tag)
    return child.text or "" if child is not None else ""


def _text(raw: str) -> str:
    return _WS.sub(" ", html.unescape(_TAG.sub(" ", str(raw or "")))).strip()


def _epoch(value: Any) -> float | None:
    """Accept unix seconds/millis, or a 'YYYY-MM-DD HH:MM:SS' local-time string."""
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        seconds = float(value)
        return seconds / 1000 if seconds > 1e11 else seconds
    text = str(value).strip()
    if text.isdigit():
        seconds = float(text)
        return seconds / 1000 if seconds > 1e11 else seconds
    return _iso(text)


def _iso(value: str) -> float | None:
    text = str(value or "").strip().replace("Z", "+00:00").replace("/", "-")
    if not text:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d",
    ):
        try:
            parsed = time.strptime(text[:32], fmt)
        except ValueError:
            continue
        try:
            return timegm(parsed) - (parsed.tm_gmtoff or 0)
        except (AttributeError, TypeError):
            return timegm(parsed)
    return None


def _rfc822(value: str) -> float | None:
    if not value:
        return None
    parsed = parsedate_tz(str(value).strip())
    if parsed:
        return timegm(parsed[:9]) - (parsed[9] or 0)
    return _iso(value)


def _fmt(ts: float) -> str:
    return time.strftime("%Y-%m-%d %H:%M", time.gmtime(ts))


def _reach(source: dict) -> str:
    flag = source.get("cn_ok")
    if flag is True:
        return "CN-reachable"
    if flag is False:
        return "needs proxy in CN"
    return "reachability unknown"


def _dedupe(items: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out = []
    for item in items:
        key = _WS.sub("", item["title"])[:60]
        if key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _cell(text: str) -> str:
    return str(text or "").replace("|", "/").replace("\n", " ").strip()[:140]
