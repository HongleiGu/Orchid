"""
WeChat Official Account (公众号) tools.

Tools:
  @orchid/wechat_publish  — create a draft article and optionally publish it
  @orchid/wechat_followers — list followers (kept for future messaging)

Uses the draft/publish API (草稿箱/发布):
  POST /cgi-bin/draft/add       — create draft
  POST /cgi-bin/freepublish/submit — publish draft

Requires WECHAT_APP_ID and WECHAT_APP_SECRET in .env.
"""
from __future__ import annotations

import json
import logging
import re
import time

import httpx

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_BASE = "https://api.weixin.qq.com/cgi-bin"

# Token cache
_token_cache: dict = {"token": "", "expires_at": 0}


class WeChatPublishTool(BaseTool):
    name = "@orchid/wechat_publish"
    description = (
        "Publish an article to WeChat Official Account. "
        "Creates a draft article and optionally publishes it immediately. "
        "Content can be plain text, markdown, or HTML. "
        "Markdown is auto-converted to HTML."
    )
    parameters = {
        "type": "object",
        "properties": {
            "title": {
                "type": "string",
                "description": "Article title.",
            },
            "content": {
                "type": "string",
                "description": "Article body. Can be markdown, plain text, or HTML.",
            },
            "author": {
                "type": "string",
                "default": "Orchid AI",
                "description": "Author name shown on the article.",
            },
            "digest": {
                "type": "string",
                "default": "",
                "description": "Brief summary shown in feed (max 120 chars). Auto-generated if empty.",
            },
            "publish": {
                "type": "boolean",
                "default": False,
                "description": "If true, publish immediately. If false, save as draft only.",
            },
        },
        "required": ["title", "content"],
    }

    async def call(
        self,
        title: str,
        content: str,
        author: str = "Orchid AI",
        digest: str = "",
        publish: bool = False,
    ) -> str:
        try:
            token = await _get_access_token()

            # Convert markdown to HTML if needed
            html_content = _to_html(content)

            # Auto-generate digest if not provided
            if not digest:
                plain = re.sub(r"<[^>]+>", "", html_content)
                digest = plain[:117] + "..." if len(plain) > 120 else plain

            # Step 1: Upload a placeholder thumb (required by API)
            thumb_media_id = await _get_or_create_thumb(token)

            # Step 2: Create draft
            draft_result = await _create_draft(
                token, title, html_content, author, digest, thumb_media_id
            )
            if draft_result.get("errcode"):
                return f"Draft creation failed: {draft_result.get('errmsg')} (code: {draft_result.get('errcode')})"

            media_id = draft_result.get("media_id", "")
            if not media_id:
                return f"Draft creation returned no media_id: {draft_result}"

            result_msg = f"Draft created successfully (media_id: {media_id})."

            # Step 3: Publish if requested
            if publish:
                pub_result = await _publish_draft(token, media_id)
                if pub_result.get("errcode", 0) != 0:
                    result_msg += f" Publish failed: {pub_result.get('errmsg')} (code: {pub_result.get('errcode')})"
                else:
                    pub_id = pub_result.get("publish_id", "unknown")
                    result_msg += f" Published (publish_id: {pub_id})."

            return result_msg

        except Exception as exc:
            logger.error("WeChat publish failed: %s", exc)
            return f"WeChat publish failed: {exc}"


class WeChatFollowersTool(BaseTool):
    name = "@orchid/wechat_followers"
    description = (
        "List followers of the WeChat Official Account. "
        "Returns OpenIDs."
    )
    parameters = {
        "type": "object",
        "properties": {
            "next_openid": {
                "type": "string",
                "default": "",
                "description": "Pagination cursor. Empty for first page.",
            },
        },
        "required": [],
    }

    async def call(self, next_openid: str = "") -> str:
        try:
            token = await _get_access_token()
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"{_BASE}/user/get",
                    params={"access_token": token, "next_openid": next_openid},
                )
                data = resp.json()

            if data.get("errcode"):
                return f"Error: {data.get('errmsg', 'Unknown error')} (code: {data.get('errcode')})"

            total = data.get("total", 0)
            count = data.get("count", 0)
            openids = data.get("data", {}).get("openid", [])
            next_id = data.get("next_openid", "")

            lines = [f"Total followers: {total}, this page: {count}"]
            for oid in openids[:20]:
                lines.append(f"  - {oid}")
            if next_id:
                lines.append(f"Next page cursor: {next_id}")

            return "\n".join(lines)
        except Exception as exc:
            return f"Failed to list followers: {exc}"


# ── Internal helpers ──────────────────────────────────────────────────────────

async def _get_access_token() -> str:
    now = time.time()
    if _token_cache["token"] and _token_cache["expires_at"] > now + 60:
        return _token_cache["token"]

    from app.config import get_settings
    settings = get_settings()
    app_id = settings.wechat_app_id
    app_secret = settings.wechat_app_secret

    if not app_id or not app_secret:
        raise ValueError("WECHAT_APP_ID or WECHAT_APP_SECRET not set")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_BASE}/token",
            params={
                "grant_type": "client_credential",
                "appid": app_id,
                "secret": app_secret,
            },
        )
        data = resp.json()

    if "access_token" not in data:
        raise ValueError(f"Token request failed: {data.get('errmsg', data)}")

    _token_cache["token"] = data["access_token"]
    _token_cache["expires_at"] = now + data.get("expires_in", 7200)
    return _token_cache["token"]


async def _create_draft(
    token: str, title: str, html_content: str, author: str, digest: str,
    thumb_media_id: str,
) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_BASE}/draft/add",
            params={"access_token": token},
            json={
                "articles": [
                    {
                        "title": title,
                        "author": author,
                        "digest": digest[:120],
                        "content": html_content,
                        "thumb_media_id": thumb_media_id,
                        "need_open_comment": 0,
                        "only_fans_can_comment": 0,
                    }
                ]
            },
        )
        return resp.json()


async def _publish_draft(token: str, media_id: str) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_BASE}/freepublish/submit",
            params={"access_token": token},
            json={"media_id": media_id},
        )
        return resp.json()


async def _get_or_create_thumb(token: str) -> str:
    """Get or upload a minimal placeholder thumbnail (required for drafts).
    Uses a 1x1 white PNG."""
    # Check if we already have one cached
    from app.db.session import AsyncSessionLocal
    from app.db.models.kv import KVStore

    try:
        async with AsyncSessionLocal() as db:
            kv = await db.get(KVStore, "wechat_thumb_media_id")
            if kv and kv.value:
                return kv.value
    except Exception:
        pass

    # Generate a 200x200 white BMP (simple format, no library needed)
    thumb_bytes = _generate_bmp(200, 200)

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_BASE}/material/add_material",
            params={"access_token": token, "type": "thumb"},
            files={"media": ("thumb.bmp", thumb_bytes, "image/bmp")},
        )
        data = resp.json()

    media_id = data.get("media_id", "")
    if not media_id:
        logger.warning("Failed to upload thumb: %s", data)
        raise ValueError(f"Thumb upload failed: {data.get('errmsg', data)}")

    # Cache it
    try:
        async with AsyncSessionLocal() as db:
            db.add(KVStore(key="wechat_thumb_media_id", value=media_id))
            await db.commit()
    except Exception:
        pass

    return media_id


def _generate_bmp(width: int, height: int) -> bytes:
    """Generate a solid-white 24-bit BMP. No external libraries needed."""
    import struct

    row_size = (width * 3 + 3) & ~3  # rows padded to 4-byte boundary
    pixel_size = row_size * height
    file_size = 54 + pixel_size  # 14 (file header) + 40 (info header) + pixels

    buf = bytearray()
    # File header (14 bytes)
    buf += b"BM"
    buf += struct.pack("<I", file_size)
    buf += b"\x00\x00\x00\x00"  # reserved
    buf += struct.pack("<I", 54)  # pixel data offset

    # Info header (40 bytes)
    buf += struct.pack("<I", 40)  # header size
    buf += struct.pack("<i", width)
    buf += struct.pack("<i", height)
    buf += struct.pack("<HH", 1, 24)  # planes, bits per pixel
    buf += struct.pack("<I", 0)  # no compression
    buf += struct.pack("<I", pixel_size)
    buf += struct.pack("<ii", 2835, 2835)  # 72 DPI
    buf += struct.pack("<II", 0, 0)  # colors

    # Pixel data (white = 0xFF for all channels)
    white_row = b"\xff" * (width * 3) + b"\x00" * (row_size - width * 3)
    buf += white_row * height

    return bytes(buf)


def _to_html(content: str) -> str:
    """Convert markdown-ish content to basic HTML for WeChat articles."""
    # If already HTML, return as-is
    if "<p>" in content or "<h1>" in content or "<div>" in content:
        return content

    lines = content.split("\n")
    html_lines: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        if not stripped:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append("<br/>")
            continue

        # Headers
        if stripped.startswith("#### "):
            html_lines.append(f"<h4>{_inline(stripped[5:])}</h4>")
        elif stripped.startswith("### "):
            html_lines.append(f"<h3>{_inline(stripped[4:])}</h3>")
        elif stripped.startswith("## "):
            html_lines.append(f"<h2>{_inline(stripped[3:])}</h2>")
        elif stripped.startswith("# "):
            html_lines.append(f"<h1>{_inline(stripped[2:])}</h1>")
        # Horizontal rule
        elif stripped in ("---", "***", "___"):
            html_lines.append("<hr/>")
        # List items
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{_inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            text = re.sub(r"^\d+\.\s", "", stripped)
            if not in_list:
                html_lines.append("<ul>")
                in_list = True
            html_lines.append(f"<li>{_inline(text)}</li>")
        else:
            if in_list:
                html_lines.append("</ul>")
                in_list = False
            html_lines.append(f"<p>{_inline(stripped)}</p>")

    if in_list:
        html_lines.append("</ul>")

    return "\n".join(html_lines)


def _inline(text: str) -> str:
    """Convert inline markdown: bold, italic, links, code."""
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Links
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    # Inline code
    text = re.sub(r"`(.+?)`", r"<code>\1</code>", text)
    return text
