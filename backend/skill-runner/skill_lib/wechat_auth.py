"""
Shared WeChat access-token cache for the wechat_* skills.

Token is fetched on demand, cached in memory, and persisted to STATE_DIR so
restarts don't burn the per-day token quota. Per-process cache is the source
of truth while running.
"""
from __future__ import annotations

import os
import time
from typing import Tuple

import httpx

from skill_lib.state import load_json, save_json

_BASE = "https://api.weixin.qq.com/cgi-bin"
_STATE_FILE = "wechat_token.json"

_cache: dict = {}


async def get_access_token() -> str:
    global _cache
    now = time.time()

    if not _cache:
        _cache = load_json(_STATE_FILE)

    if _cache.get("token") and _cache.get("expires_at", 0) > now + 60:
        return _cache["token"]

    app_id = os.environ.get("WECHAT_APP_ID", "")
    app_secret = os.environ.get("WECHAT_APP_SECRET", "")
    if not app_id or not app_secret:
        raise ValueError("WECHAT_APP_ID or WECHAT_APP_SECRET not set")

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(
            f"{_BASE}/token",
            params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
        )
        data = resp.json()

    if "access_token" not in data:
        raise ValueError(f"WeChat token request failed: {data.get('errmsg', data)}")

    _cache = {
        "token": data["access_token"],
        "expires_at": now + data.get("expires_in", 7200),
    }
    save_json(_STATE_FILE, _cache)
    return _cache["token"]


async def get_or_create_thumb(token: str) -> str:
    """Get the cached placeholder thumb media_id, or upload a new one."""
    state = load_json("wechat_thumb.json")
    if state.get("media_id"):
        return state["media_id"]

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
        raise ValueError(f"WeChat thumb upload failed: {data.get('errmsg', data)}")

    save_json("wechat_thumb.json", {"media_id": media_id})
    return media_id


def _generate_bmp(width: int, height: int) -> bytes:
    """Solid-white 24-bit BMP — no external libs."""
    import struct

    row_size = (width * 3 + 3) & ~3
    pixel_size = row_size * height
    file_size = 54 + pixel_size

    buf = bytearray()
    buf += b"BM"
    buf += struct.pack("<I", file_size)
    buf += b"\x00\x00\x00\x00"
    buf += struct.pack("<I", 54)

    buf += struct.pack("<I", 40)
    buf += struct.pack("<i", width)
    buf += struct.pack("<i", height)
    buf += struct.pack("<HH", 1, 24)
    buf += struct.pack("<I", 0)
    buf += struct.pack("<I", pixel_size)
    buf += struct.pack("<ii", 2835, 2835)
    buf += struct.pack("<II", 0, 0)

    white_row = b"\xff" * (width * 3) + b"\x00" * (row_size - width * 3)
    buf += white_row * height
    return bytes(buf)
