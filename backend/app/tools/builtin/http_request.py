from __future__ import annotations

import httpx

from app.tools.base import BaseTool

_MAX_RESPONSE_CHARS = 8_000


class HttpRequestTool(BaseTool):
    name = "@orchid/http_request"
    description = "Make an HTTP GET or POST request to a URL and return the response body."
    parameters = {
        "type": "object",
        "properties": {
            "url": {"type": "string", "description": "The target URL."},
            "method": {
                "type": "string",
                "enum": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                "default": "GET",
            },
            "body": {
                "type": "object",
                "description": "JSON body for POST/PUT/PATCH requests.",
            },
            "headers": {"type": "object", "description": "Additional HTTP headers."},
        },
        "required": ["url"],
    }

    async def call(
        self,
        url: str,
        method: str = "GET",
        body: dict | None = None,
        headers: dict | None = None,
    ) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.request(
                method, url, json=body, headers=headers or {}
            )
        return resp.text[:_MAX_RESPONSE_CHARS]
