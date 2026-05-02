"""
Gmail OAuth token loader/refresher.

Tokens are written to STATE_DIR by the backend's OAuth callback. The skill
reads them, refreshes the access_token when it's about to expire, and writes
the refreshed copy back so the backend sees up-to-date state.
"""
from __future__ import annotations

import os
import time

import httpx

from skill_lib.state import load_json, save_json

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_STATE_FILE = "gmail_tokens.json"


async def get_valid_token() -> str | None:
    """Return a valid access token, refreshing if needed. None if not authorized."""
    tokens = load_json(_STATE_FILE)
    if not tokens.get("refresh_token"):
        return None

    if tokens.get("access_token") and tokens.get("expires_at", 0) > time.time() + 60:
        return tokens["access_token"]

    client_id = os.environ.get("GMAIL_CLIENT_ID", "")
    client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
    if not client_id or not client_secret:
        return None

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(_TOKEN_URL, data={
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": tokens["refresh_token"],
            "grant_type": "refresh_token",
        })
        data = resp.json()

    if "access_token" not in data:
        return None

    tokens["access_token"] = data["access_token"]
    tokens["expires_at"] = time.time() + data.get("expires_in", 3600)
    save_json(_STATE_FILE, tokens)
    return tokens["access_token"]
