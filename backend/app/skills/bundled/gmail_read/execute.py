from __future__ import annotations

import logging

import httpx

from skill_lib.gmail_auth import get_valid_token

logger = logging.getLogger(__name__)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


async def execute(query: str = "", max_results: int = 5) -> str:
    try:
        token = await get_valid_token()
        if not token:
            return "Error: Gmail not authorized. Visit /api/v1/gmail/auth to set up."

        async with httpx.AsyncClient(timeout=15) as client:
            params: dict = {"maxResults": max_results}
            if query:
                params["q"] = query
            resp = await client.get(
                f"{_GMAIL_API}/users/me/messages",
                headers={"Authorization": f"Bearer {token}"},
                params=params,
            )
            data = resp.json()

        messages = data.get("messages", [])
        if not messages:
            return "No emails found."

        results = []
        async with httpx.AsyncClient(timeout=15) as client:
            for msg in messages[:max_results]:
                detail = await client.get(
                    f"{_GMAIL_API}/users/me/messages/{msg['id']}",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"format": "metadata", "metadataHeaders": ["From", "Subject", "Date"]},
                )
                d = detail.json()
                headers = {h["name"]: h["value"] for h in d.get("payload", {}).get("headers", [])}
                results.append(
                    f"- **{headers.get('Subject', '(no subject)')}**\n"
                    f"  From: {headers.get('From', '?')} | {headers.get('Date', '?')}\n"
                    f"  {d.get('snippet', '')[:200]}"
                )
        return "\n\n".join(results)
    except Exception as exc:
        logger.error("Gmail read failed: %s", exc)
        return f"Gmail read failed: {exc}"
