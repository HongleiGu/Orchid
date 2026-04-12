"""
Web page reader — fetches a URL and extracts clean text content.

Handles:
  - Regular HTML pages (strips tags, scripts, styles, nav)
  - Google Scholar profiles
  - Faculty/lab pages
  - PDF links (returns first N chars via basic extraction)

Uses only httpx + stdlib (no beautifulsoup dependency in skill-runner).
"""
from __future__ import annotations

import logging
import re
from html.parser import HTMLParser

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Tags whose content we skip entirely
_SKIP_TAGS = {"script", "style", "noscript", "svg", "path", "nav", "footer", "header"}


async def execute(url: str, max_chars: int = 8000, selector: str = "") -> str:
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        content_type = resp.headers.get("content-type", "")

        if "application/pdf" in content_type:
            return _extract_pdf_text(resp.content, max_chars)

        html = resp.text
        text = _html_to_text(html)

        # If selector keyword provided, try to focus on that section
        if selector and len(text) > max_chars:
            focused = _focus_on_section(text, selector, max_chars)
            if focused:
                text = focused

        if len(text) > max_chars:
            text = text[:max_chars] + "\n\n[... truncated]"

        # Extract links that might be useful (publications, PDFs, lab pages)
        links = _extract_useful_links(html, url)
        if links:
            text += "\n\n---\n**Relevant links found on page:**\n"
            for label, href in links[:15]:
                text += f"- [{label}]({href})\n"

        return f"**Content from {url}:**\n\n{text}" if text.strip() else f"No readable content found at {url}"

    except httpx.HTTPStatusError as exc:
        return f"HTTP error {exc.response.status_code} fetching {url}"
    except Exception as exc:
        return f"Failed to read {url}: {exc}"


class _TextExtractor(HTMLParser):
    """Simple HTML→text converter."""

    def __init__(self):
        super().__init__()
        self.result: list[str] = []
        self._skip_depth = 0
        self._in_skip = False

    def handle_starttag(self, tag, attrs):
        tag_lower = tag.lower()
        if tag_lower in _SKIP_TAGS:
            self._skip_depth += 1
            self._in_skip = True
        elif tag_lower in ("br", "hr"):
            self.result.append("\n")
        elif tag_lower in ("p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.result.append("\n")
        elif tag_lower == "a":
            pass  # handled in handle_data

    def handle_endtag(self, tag):
        tag_lower = tag.lower()
        if tag_lower in _SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            if self._skip_depth == 0:
                self._in_skip = False
        elif tag_lower in ("p", "div", "li", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.result.append("\n")

    def handle_data(self, data):
        if not self._in_skip:
            self.result.append(data)

    def get_text(self) -> str:
        raw = "".join(self.result)
        # Collapse whitespace
        lines = []
        for line in raw.split("\n"):
            cleaned = " ".join(line.split())
            if cleaned:
                lines.append(cleaned)
        return "\n".join(lines)


def _html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.get_text()


def _focus_on_section(text: str, keyword: str, max_chars: int) -> str:
    """Find the section around a keyword and return centered context."""
    keyword_lower = keyword.lower()
    idx = text.lower().find(keyword_lower)
    if idx < 0:
        return ""

    # Take a window around the keyword
    window = max_chars
    start = max(0, idx - window // 4)  # more after than before
    end = min(len(text), idx + window * 3 // 4)
    section = text[start:end]

    if start > 0:
        section = "[...]\n" + section
    if end < len(text):
        section += "\n[...]"

    return section


def _extract_useful_links(html: str, base_url: str) -> list[tuple[str, str]]:
    """Extract links that look like publications, lab pages, etc."""
    from urllib.parse import urljoin

    pattern = re.compile(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )

    keywords = {
        "publication", "paper", "research", "project", "student",
        "phd", "lab", "group", "team", "openings", "join",
        "cv", "resume", "scholar", "dblp", "arxiv",
    }

    links: list[tuple[str, str]] = []
    seen_urls: set[str] = set()

    for match in pattern.finditer(html):
        href = match.group(1).strip()
        label = re.sub(r"<[^>]+>", "", match.group(2)).strip()

        if not href or href.startswith("#") or href.startswith("javascript:"):
            continue

        full_url = urljoin(base_url, href)
        if full_url in seen_urls:
            continue

        # Check if link text or URL contains relevant keywords
        text_lower = (label + " " + href).lower()
        if any(kw in text_lower for kw in keywords) or href.endswith(".pdf"):
            seen_urls.add(full_url)
            display = label[:80] if label else full_url
            links.append((display, full_url))

    return links


def _extract_pdf_text(content: bytes, max_chars: int) -> str:
    """Very basic PDF text extraction — looks for text streams."""
    try:
        text = content.decode("latin-1", errors="replace")
        # Find text between BT and ET markers (PDF text objects)
        chunks = re.findall(r"\(([^)]+)\)", text)
        readable = " ".join(c for c in chunks if len(c) > 3 and c.isprintable())
        if readable:
            return readable[:max_chars]
    except Exception:
        pass
    return "[PDF content — could not extract text. Download the file for full content.]"
