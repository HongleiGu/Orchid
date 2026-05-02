from __future__ import annotations

import httpx

_MAX_RESPONSE_CHARS = 8_000


async def execute(
    url: str,
    method: str = "GET",
    body: dict | None = None,
    headers: dict | None = None,
) -> str:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.request(method, url, json=body, headers=headers or {})
    return resp.text[:_MAX_RESPONSE_CHARS]
