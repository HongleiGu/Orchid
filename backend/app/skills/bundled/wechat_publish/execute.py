from __future__ import annotations

import logging
import mimetypes
import re

import httpx

from skill_lib.markdown import to_html
from skill_lib.vault import resolve_vault_path
from skill_lib.wechat_auth import get_access_token, get_or_create_thumb

logger = logging.getLogger(__name__)

_BASE = "https://api.weixin.qq.com/cgi-bin"


async def execute(
    title: str,
    content: str,
    author: str = "Orchid AI",
    digest: str = "",
    publish: bool = False,
) -> str:
    try:
        token = await get_access_token()

        html_content = _to_wechat_html(content)
        html_content = await _rewrite_local_images(token, html_content)

        if not digest:
            plain = re.sub(r"<[^>]+>", "", html_content)
            digest = plain[:117] + "..." if len(plain) > 120 else plain

        thumb_media_id = await get_or_create_thumb(token)
        draft = await _create_draft(token, title, html_content, author, digest, thumb_media_id)
        if draft.get("errcode"):
            return f"Draft creation failed: {draft.get('errmsg')} (code: {draft.get('errcode')})"

        media_id = draft.get("media_id", "")
        if not media_id:
            return f"Draft creation returned no media_id: {draft}"

        msg = f"Draft created successfully (media_id: {media_id})."
        if publish:
            pub = await _publish_draft(token, media_id)
            if pub.get("errcode", 0) != 0:
                msg += f" Publish failed: {pub.get('errmsg')} (code: {pub.get('errcode')})"
            else:
                msg += f" Published (publish_id: {pub.get('publish_id', 'unknown')})."
        return msg
    except Exception as exc:
        logger.error("WeChat publish failed: %s", exc)
        return f"WeChat publish failed: {exc}"


def _to_wechat_html(content: str) -> str:
    if "<p>" in content or "<h1>" in content or "<div>" in content:
        return content
    return to_html(content, style="wechat")


async def _create_draft(token, title, html_content, author, digest, thumb_media_id) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_BASE}/draft/add",
            params={"access_token": token},
            json={"articles": [{
                "title": title,
                "author": author,
                "digest": digest[:120],
                "content": html_content,
                "thumb_media_id": thumb_media_id,
                "need_open_comment": 0,
                "only_fans_can_comment": 0,
            }]},
        )
        return resp.json()


async def _publish_draft(token, media_id) -> dict:
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{_BASE}/freepublish/submit",
            params={"access_token": token},
            json={"media_id": media_id},
        )
        return resp.json()


async def _upload_image(token, path) -> str:
    mime, _ = mimetypes.guess_type(path.name)
    mime = mime or "image/png"
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{_BASE}/media/uploadimg",
            params={"access_token": token},
            files={"media": (path.name, path.read_bytes(), mime)},
        )
        data = resp.json()
    if data.get("errcode"):
        raise ValueError(f"uploadimg failed: {data}")
    url = data.get("url")
    if not url:
        raise ValueError(f"uploadimg returned no url: {data}")
    return url


async def _rewrite_local_images(token: str, html: str) -> str:
    pattern = re.compile(r'<img\s+[^>]*src=["\']([^"\']+)["\']', re.IGNORECASE)
    cache: dict[str, str] = {}
    srcs = list({m.group(1) for m in pattern.finditer(html)})
    for src in srcs:
        if src.startswith(("http://", "https://", "data:")):
            continue
        local = resolve_vault_path(src)
        if not local:
            logger.warning("WeChat: image not found, leaving src as-is: %s", src)
            continue
        try:
            cache[src] = await _upload_image(token, local)
        except Exception as exc:
            logger.warning("WeChat upload failed for %s: %s", src, exc)

    def repl(m: re.Match) -> str:
        src = m.group(1)
        return m.group(0).replace(src, cache[src]) if src in cache else m.group(0)

    return pattern.sub(repl, html)
