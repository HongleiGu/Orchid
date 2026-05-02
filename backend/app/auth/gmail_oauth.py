"""
Gmail OAuth state — backend side.

The OAuth callback writes tokens to STATE_DIR/gmail_tokens.json. The
@orchid/gmail_send and @orchid/gmail_read skills (running in skill-runner)
read from the same file via its STATE_DIR mount.

No DB involvement: the file is the source of truth, simpler for an OSS
single-tenant deploy. Multi-tenant comes via the platform layer's secret
broker (future.md Tier 1.3 / Tier 3.2).
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import httpx

from app.config import get_settings

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_STATE_FILE = "gmail_tokens.json"


def _state_dir() -> Path:
    p = Path(os.environ.get("STATE_DIR", "/app/data/state"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_tokens() -> dict:
    path = _state_dir() / _STATE_FILE
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_tokens(tokens: dict) -> None:
    path = _state_dir() / _STATE_FILE
    path.write_text(json.dumps(tokens, indent=2), encoding="utf-8")


async def exchange_code(code: str, redirect_uri: str) -> dict:
    """Exchange an OAuth authorization code for access + refresh tokens."""
    s = get_settings()
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(_TOKEN_URL, data={
            "code": code,
            "client_id": s.gmail_client_id,
            "client_secret": s.gmail_client_secret,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        })
        data = resp.json()

    if "access_token" not in data:
        raise ValueError(f"Token exchange failed: {data}")

    tokens = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": time.time() + data.get("expires_in", 3600),
    }
    save_tokens(tokens)
    return tokens
