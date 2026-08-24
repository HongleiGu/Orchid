"""Fetch web pages and return readable text.

Deliberately dependency-free (no readability/bs4 in the runner image): a
regex-based strip is enough to turn a news article into text an LLM can quote,
and it degrades predictably on pages it cannot parse.
"""
from __future__ import annotations

import asyncio
import html
import re

import httpx

_TIMEOUT = 25
_MAX_URLS = 8
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

_DROP_BLOCKS = re.compile(
    r"<(script|style|noscript|svg|iframe|nav|header|footer|aside|form)\b[^>]*>.*?</\1>",
    re.IGNORECASE | re.DOTALL,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_BLOCK_END = re.compile(
    r"</(p|div|section|article|li|tr|h[1-6]|blockquote)>", re.IGNORECASE
)
_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
_TAG = re.compile(r"<[^>]+>")
_WS_RUN = re.compile(r"[ \t\xa0　]+")
_NL_RUN = re.compile(r"\n{3,}")


async def execute(
    url: str | None = None,
    urls: list[str] | None = None,
    max_chars: int = 6000,
) -> str:
    targets: list[str] = []
    for candidate in [url, *(urls or [])]:
        clean = str(candidate or "").strip()
        if clean and clean not in targets:
            targets.append(clean)
    if not targets:
        return "Error: provide `url` or a non-empty `urls` list."
    targets = targets[:_MAX_URLS]

    budget = max(500, min(int(max_chars or 6000), 20_000))

    async with httpx.AsyncClient(
        timeout=_TIMEOUT,
        follow_redirects=True,
        headers={
            "User-Agent": _UA,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        },
    ) as client:
        pages = await asyncio.gather(
            *[_fetch(client, t, budget) for t in targets], return_exceptions=True
        )

    sections = [f"# Fetched pages ({len(targets)})", ""]
    ok = 0
    for target, page in zip(targets, pages):
        if isinstance(page, Exception):
            sections.append(f"## FAILED: {target}\n`{type(page).__name__}: {page}`\n")
            continue
        ok += 1
        sections.append(
            f"## {page['title']}\n"
            f"- URL: {page['url']}\n"
            f"- HTTP: {page['status']} | charset: {page['charset']} | "
            f"extracted: {page['chars']} chars\n\n"
            f"{page['text']}\n"
        )
    sections.insert(1, f"{ok}/{len(targets)} pages read successfully.\n")
    return "\n".join(sections)


async def _fetch(client: httpx.AsyncClient, url: str, budget: int) -> dict:
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    resp = await client.get(url)
    body = _decode(resp)
    title = ""
    match = _TITLE.search(body)
    if match:
        title = _clean(_TAG.sub("", html.unescape(match.group(1))))
    text = _extract(body)
    return {
        "title": title[:200] or url,
        "url": str(resp.url),
        "status": resp.status_code,
        "charset": resp.encoding or "unknown",
        "chars": len(text),
        "text": text[:budget] + ("\n... [truncated]" if len(text) > budget else ""),
    }


def _decode(resp: httpx.Response) -> str:
    """Decode a response body, tolerating mainland pages that mis-declare charset.

    httpx defaults to utf-8 when no charset is declared; a GB18030 page decoded
    that way comes back as replacement characters, so retry on a high ratio of
    them.
    """
    raw = resp.content
    declared = (resp.charset_encoding or "").lower()
    candidates = [declared] if declared else []
    head = raw[:2048].decode("ascii", "ignore").lower()
    for guess in ("gb18030", "gbk", "gb2312", "big5", "utf-8"):
        if guess in head and guess not in candidates:
            candidates.append(guess)
    candidates.extend(["utf-8", "gb18030"])

    best = ""
    for enc in candidates:
        if not enc:
            continue
        try:
            decoded = raw.decode(enc, errors="replace")
        except LookupError:
            continue
        if decoded.count("�") <= max(5, len(decoded) // 500):
            return decoded
        best = best or decoded
    return best or raw.decode("utf-8", errors="replace")


def _extract(body: str) -> str:
    body = _DROP_BLOCKS.sub(" ", body)
    body = _BR.sub("\n", body)
    body = _BLOCK_END.sub("\n", body)
    body = _TAG.sub(" ", body)
    body = html.unescape(body)
    lines = [_clean(line) for line in body.split("\n")]
    # Drop nav crumbs and menu noise: very short lines with no sentence content.
    kept = [ln for ln in lines if len(ln) > 2]
    return _NL_RUN.sub("\n\n", "\n".join(kept)).strip()


def _clean(text: str) -> str:
    return _WS_RUN.sub(" ", text).strip()
