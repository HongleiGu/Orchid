from __future__ import annotations

import json
import logging
import mimetypes

import httpx

from skill_lib.vault import resolve_vault_path
from skill_lib.wechat_auth import get_access_token

logger = logging.getLogger(__name__)

_BASE = "https://api.weixin.qq.com/cgi-bin"


async def execute(path: str) -> str:
    try:
        token = await get_access_token()
        local = resolve_vault_path(path)
        if not local:
            return f"Image not found: {path}"

        mime, _ = mimetypes.guess_type(local.name)
        mime = mime or "image/png"
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_BASE}/media/uploadimg",
                params={"access_token": token},
                files={"media": (local.name, local.read_bytes(), mime)},
            )
            data = resp.json()
        if data.get("errcode"):
            return f"WeChat upload failed: {data}"
        url = data.get("url")
        if not url:
            return f"WeChat upload returned no url: {data}"
        return json.dumps({"type": "image", "path": str(local), "wechat_url": url})
    except Exception as exc:
        logger.error("WeChat upload failed: %s", exc)
        return f"WeChat upload failed: {exc}"
