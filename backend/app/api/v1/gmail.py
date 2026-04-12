"""
Gmail OAuth flow endpoints.

1. GET  /api/v1/gmail/auth     → redirects to Google consent screen
2. GET  /api/v1/gmail/callback → receives auth code, exchanges for tokens
3. GET  /api/v1/gmail/status   → check if Gmail is authorized
"""
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from app.api.schemas import DataResponse
from app.config import get_settings

router = APIRouter(prefix="/gmail", tags=["gmail"])

_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_SCOPES = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"


def _redirect_uri(request: Request) -> str:
    """Build the OAuth redirect URI from the current request."""
    return str(request.url_for("gmail_callback"))


@router.get("/auth")
async def gmail_auth(request: Request):
    """Start the Gmail OAuth consent flow."""
    s = get_settings()
    if not s.gmail_client_id:
        raise HTTPException(400, "GMAIL_CLIENT_ID not set in .env")

    params = {
        "client_id": s.gmail_client_id,
        "redirect_uri": _redirect_uri(request),
        "response_type": "code",
        "scope": _SCOPES,
        "access_type": "offline",
        "prompt": "consent",
    }
    return RedirectResponse(f"{_AUTH_URL}?{urlencode(params)}")


@router.get("/callback")
async def gmail_callback(request: Request, code: str = ""):
    """OAuth callback — exchange code for tokens."""
    if not code:
        raise HTTPException(400, "Missing authorization code")

    from app.tools.builtin.gmail import save_initial_tokens

    try:
        tokens = await save_initial_tokens(code, _redirect_uri(request))
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    return HTMLResponse(
        "<html><body style='font-family:sans-serif;padding:40px;text-align:center'>"
        "<h2>Gmail authorized successfully</h2>"
        "<p>You can close this tab and return to Orchid.</p>"
        "<p>The <code>@orchid/gmail_send</code> and <code>@orchid/gmail_read</code> "
        "tools are now available.</p>"
        "</body></html>"
    )


@router.get("/status", response_model=DataResponse[dict])
async def gmail_status():
    """Check if Gmail OAuth tokens are saved."""
    from app.tools.builtin.gmail import _load_tokens_from_db

    tokens = await _load_tokens_from_db()
    authorized = bool(tokens.get("refresh_token"))
    return DataResponse(data={"authorized": authorized})
