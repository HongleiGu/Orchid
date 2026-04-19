"""
Web page reader — fetches a URL and returns clean, query-focused text.

Token-efficiency strategy (mirrors how Claude Code's WebFetch behaves):
  - Strip noise (script/style/nav/footer/aside/forms/iframes + cookie/popup
    class names) before doing anything else.
  - Prefer the <main> or <article> body when present — most page boilerplate
    lives outside it.
  - Preserve structure as light markdown (#, -, [text](url) inline) so the
    LLM still sees headings/lists without wading through HTML.
  - When `query` is set, score paragraphs by query-term overlap and return
    only the relevant ones (+/- 1 neighbor for context). This is the largest
    single saving.
  - Truncate at paragraph/sentence boundary, never mid-word.
"""
from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from urllib.parse import urljoin

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT = 15
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
# Tags whose entire subtree we drop
_SKIP_TAGS = {
    "script", "style", "noscript", "svg", "path", "iframe",
    "nav", "footer", "header", "aside", "form", "button",
}
# Class/id substrings that mark obvious noise
_NOISE_CLASSES = (
    "cookie", "consent", "newsletter", "subscribe", "popup", "modal",
    "advert", "promo", "sidebar", "social-share", "comments", "related-posts",
)
_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
_BLOCK_TAGS = {"p", "div", "section", "tr", "blockquote", "pre"}
_MAIN_RE = re.compile(r"<(main|article)\b[^>]*>(.*?)</\1>", re.IGNORECASE | re.DOTALL)


async def execute(
    url: str,
    max_chars: int = 3000,
    selector: str = "",
    query: str = "",
) -> str:
    try:
        async with httpx.AsyncClient(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            resp = await client.get(url)
            resp.raise_for_status()

        ctype = resp.headers.get("content-type", "")
        if "application/pdf" in ctype:
            text = _extract_pdf_text(resp.content, max_chars)
            return f"# {url}\n\n{text}"

        html = resp.text
        body = _isolate_main(html)
        text = _html_to_markdown(body, base_url=url)

        if query:
            text = _select_by_query(text, query, max_chars)
        elif selector:
            focused = _focus_on_section(text, selector, max_chars)
            if focused:
                text = focused

        if len(text) > max_chars:
            text = _truncate_at_boundary(text, max_chars) + "\n\n[... truncated]"

        links = _extract_useful_links(html, url)
        if links:
            text += "\n\n---\nLinks:\n" + "\n".join(
                f"- [{label}]({href})" for label, href in links[:5]
            )

        if not text.strip():
            return f"No readable content at {url}"
        return f"# {url}\n\n{text}"

    except httpx.HTTPStatusError as exc:
        return f"HTTP {exc.response.status_code} fetching {url}"
    except Exception as exc:
        return f"Failed to read {url}: {exc}"


# ── HTML processing ─────────────────────────────────────────────────────────


def _isolate_main(html: str) -> str:
    """Return the largest <main>/<article> block, else original html."""
    matches = _MAIN_RE.findall(html)
    if not matches:
        return html
    return max((body for _, body in matches), key=len)


class _MarkdownExtractor(HTMLParser):
    """HTML → light-markdown: headings as #, lists as -, inline [text](url)."""

    def __init__(self, base_url: str = "") -> None:
        super().__init__()
        self.base_url = base_url
        self.parts: list[str] = []
        self._skip_stack: list[str] = []
        self._href: str | None = None
        self._href_text: list[str] = []

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        attr_dict = dict(attrs)
        cls = (attr_dict.get("class", "") + " " + attr_dict.get("id", "")).lower()

        if tag in _SKIP_TAGS or any(n in cls for n in _NOISE_CLASSES):
            self._skip_stack.append(tag)
            return
        if self._skip_stack:
            return

        if tag in _HEADING_TAGS:
            self.parts.append("\n\n" + "#" * int(tag[1]) + " ")
        elif tag == "li":
            self.parts.append("\n- ")
        elif tag in ("br", "hr"):
            self.parts.append("\n")
        elif tag in _BLOCK_TAGS:
            self.parts.append("\n\n")
        elif tag == "a":
            self._href = attr_dict.get("href", "").strip()
            self._href_text = []

    def handle_endtag(self, tag):
        tag = tag.lower()
        if self._skip_stack:
            # Pop back to (and including) the matching opener; tolerates
            # malformed HTML by collapsing unclosed inner tags.
            if tag in self._skip_stack:
                while self._skip_stack and self._skip_stack[-1] != tag:
                    self._skip_stack.pop()
                if self._skip_stack:
                    self._skip_stack.pop()
            return
        if tag == "a" and self._href is not None:
            label = "".join(self._href_text).strip()
            if label and self._href and not self._href.startswith(("#", "javascript:")):
                full = urljoin(self.base_url, self._href) if self.base_url else self._href
                self.parts.append(f"[{label}]({full})")
            else:
                self.parts.append(label)
            self._href = None
            self._href_text = []
        elif tag in _HEADING_TAGS:
            self.parts.append("\n")

    def handle_data(self, data):
        if self._skip_stack:
            return
        if self._href is not None:
            self._href_text.append(data)
        else:
            self.parts.append(data)

    def get_markdown(self) -> str:
        raw = "".join(self.parts)
        # Per-line whitespace collapse, then global blank-line collapse
        lines = [" ".join(line.split()) for line in raw.split("\n")]
        joined = "\n".join(lines)
        joined = re.sub(r"\n{3,}", "\n\n", joined)
        return _drop_nav_lines(joined).strip()


def _html_to_markdown(html: str, base_url: str = "") -> str:
    parser = _MarkdownExtractor(base_url=base_url)
    try:
        parser.feed(html)
    except Exception:
        pass
    return parser.get_markdown()


_NAVISH_RE = re.compile(r"^[A-Z][\w &-]{0,20}$")


def _drop_nav_lines(text: str) -> str:
    """Drop runs of short capitalized lines — the residue of menu items that
    survived the structural strip (common when nav lives in plain divs)."""
    lines = text.split("\n")
    keep: list[str] = []
    short_run = 0
    for line in lines:
        if not line.strip():
            short_run = 0
            keep.append(line)
            continue
        if (
            len(line) < 25
            and not line.startswith(("#", "-", ">", "["))
            and _NAVISH_RE.match(line)
        ):
            short_run += 1
            if short_run > 2:
                continue
        else:
            short_run = 0
        keep.append(line)
    return "\n".join(keep)


# ── Selection / truncation ──────────────────────────────────────────────────


def _select_by_query(text: str, query: str, max_chars: int) -> str:
    """Return paragraphs ranked by query-term overlap, with ±1 neighbor for context."""
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return text

    q_terms = {t.lower() for t in re.findall(r"\w+", query) if len(t) > 2}
    if not q_terms:
        return text

    def score(p: str) -> int:
        words = re.findall(r"\w+", p.lower())
        return sum(1 for w in words if w in q_terms)

    hit_idxs = {i for i, p in enumerate(paras) if score(p) > 0}
    if not hit_idxs:
        return text

    chosen = set(hit_idxs)
    for i in list(hit_idxs):
        if i > 0:
            chosen.add(i - 1)
        if i + 1 < len(paras):
            chosen.add(i + 1)

    selected = "\n\n".join(paras[i] for i in sorted(chosen))
    if len(selected) > max_chars:
        selected = _truncate_at_boundary(selected, max_chars) + "\n\n[... truncated]"
    return f"_(filtered to paragraphs matching '{query}')_\n\n{selected}"


def _focus_on_section(text: str, keyword: str, max_chars: int) -> str:
    idx = text.lower().find(keyword.lower())
    if idx < 0:
        return ""
    start = max(0, idx - max_chars // 4)
    end = min(len(text), idx + max_chars * 3 // 4)
    section = text[start:end]
    if start > 0:
        section = "[...]\n" + section
    if end < len(text):
        section += "\n[...]"
    return section


def _truncate_at_boundary(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    cut = text[:max_chars]
    p = cut.rfind("\n\n")
    if p > max_chars * 0.7:
        return cut[:p].rstrip()
    for punc in (". ", "! ", "? ", ".\n", "!\n", "?\n"):
        s = cut.rfind(punc)
        if s > max_chars * 0.7:
            return cut[:s + 1].rstrip()
    w = cut.rfind(" ")
    return (cut[:w] if w > 0 else cut).rstrip()


# ── Links ───────────────────────────────────────────────────────────────────

_LINK_KEYWORDS = {
    "publication", "paper", "research", "project", "student",
    "phd", "lab", "group", "team", "openings", "join",
    "cv", "resume", "scholar", "dblp", "arxiv",
}


def _extract_useful_links(html: str, base_url: str) -> list[tuple[str, str]]:
    pattern = re.compile(
        r'<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        re.IGNORECASE | re.DOTALL,
    )
    links: list[tuple[str, str]] = []
    seen: set[str] = set()
    for m in pattern.finditer(html):
        href = m.group(1).strip()
        label = re.sub(r"<[^>]+>", "", m.group(2)).strip()
        if not href or href.startswith(("#", "javascript:")):
            continue
        full = urljoin(base_url, href)
        if full in seen:
            continue
        scope = (label + " " + href).lower()
        if any(kw in scope for kw in _LINK_KEYWORDS) or href.endswith(".pdf"):
            seen.add(full)
            links.append((label[:80] if label else full, full))
    return links


# ── PDF ─────────────────────────────────────────────────────────────────────


def _extract_pdf_text(content: bytes, max_chars: int) -> str:
    """Prefer pypdf; fall back to a regex scrape that catches simple text streams."""
    try:
        from io import BytesIO
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(content))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages[:10])
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if text:
            return _truncate_at_boundary(text, max_chars)
    except Exception:
        pass
    try:
        text = content.decode("latin-1", errors="replace")
        chunks = re.findall(r"\(([^)]+)\)", text)
        readable = " ".join(c for c in chunks if len(c) > 3 and c.isprintable())
        if readable:
            return _truncate_at_boundary(readable, max_chars)
    except Exception:
        pass
    return "[PDF — could not extract text. Download for full content.]"
