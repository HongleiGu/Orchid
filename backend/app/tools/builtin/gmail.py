"""
Gmail tool — send emails via Gmail API using OAuth2.

Setup flow:
1. Set GMAIL_CLIENT_ID and GMAIL_CLIENT_SECRET in .env
2. Visit /api/v1/gmail/auth to start the OAuth consent flow
3. Authorize in browser → redirects back with tokens
4. Tokens are saved to DB — tool is ready to use

Requires: httpx (already in deps)
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import logging
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_SCOPES = "https://www.googleapis.com/auth/gmail.send https://www.googleapis.com/auth/gmail.readonly"

# In-memory token cache (loaded from DB on first use)
_token_cache: dict = {}


class GmailSendTool(BaseTool):
    name = "@orchid/gmail_send"
    description = (
        "Send an email via Gmail. Supports plain text and HTML content. "
        "Requires Gmail OAuth to be set up first (visit /api/v1/gmail/auth)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "to": {
                "type": "string",
                "description": "Recipient email address.",
            },
            "subject": {
                "type": "string",
                "description": "Email subject line.",
            },
            "body": {
                "type": "string",
                "description": "Email body content (plain text or HTML).",
            },
            "html": {
                "type": "boolean",
                "default": False,
                "description": "Whether body is HTML.",
            },
            "cc": {
                "type": "string",
                "default": "",
                "description": "CC recipients (comma-separated).",
            },
        },
        "required": ["to", "subject", "body"],
    }

    async def call(
        self,
        to: str,
        subject: str,
        body: str,
        html: bool = False,
        cc: str = "",
    ) -> str:
        try:
            token = await _get_valid_token()
            if not token:
                return "Error: Gmail not authorized. Visit /api/v1/gmail/auth to set up."

            msg = _build_message(to, subject, body, html, cc)
            raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("ascii")

            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{_GMAIL_API}/users/me/messages/send",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"raw": raw},
                )
                data = resp.json()

            if resp.status_code != 200:
                return f"Error: {data.get('error', {}).get('message', resp.text)}"

            return f"Email sent successfully (id: {data.get('id', 'unknown')})."
        except Exception as exc:
            logger.error("Gmail send failed: %s", exc)
            return f"Gmail send failed: {exc}"


class GmailReadTool(BaseTool):
    name = "@orchid/gmail_read"
    description = (
        "Read recent emails from Gmail inbox. "
        "Returns subject, sender, and snippet for each message."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "default": "",
                "description": "Gmail search query (e.g. 'from:alice', 'is:unread', 'subject:report').",
            },
            "max_results": {
                "type": "integer",
                "default": 5,
                "description": "Number of emails to return.",
            },
        },
        "required": [],
    }

    async def call(self, query: str = "", max_results: int = 5) -> str:
        try:
            token = await _get_valid_token()
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


# ── Email builder ─────────────────────────────────────────────────────────────

def _build_message(
    to: str, subject: str, body: str, html: bool = False, cc: str = ""
) -> MIMEMultipart:
    msg = MIMEMultipart("alternative")
    msg["To"] = to
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = cc

    if html:
        # Already HTML
        msg.attach(MIMEText(body, "plain"))  # fallback
        msg.attach(MIMEText(body, "html"))
    elif _looks_like_markdown(body):
        # Auto-convert markdown → styled HTML
        html_body = _md_to_html(body)
        msg.attach(MIMEText(body, "plain"))       # plain text fallback
        msg.attach(MIMEText(html_body, "html"))   # rich HTML version
    else:
        msg.attach(MIMEText(body, "plain"))

    return msg


def _looks_like_markdown(text: str) -> bool:
    """Detect if text contains markdown formatting."""
    import re
    indicators = [
        r"^#{1,6}\s",       # headers
        r"\*\*.+\*\*",      # bold
        r"^\s*[-*]\s",       # list items
        r"^\s*\d+\.\s",     # numbered lists
        r"\[.+\]\(.+\)",    # links
        r"^>\s",             # blockquotes
        r"```",              # code blocks
        r"^---\s*$",         # horizontal rules
    ]
    for pattern in indicators:
        if re.search(pattern, text, re.MULTILINE):
            return True
    return False


def _md_to_html(md: str) -> str:
    """Convert markdown to styled HTML email."""
    import re

    lines = md.split("\n")
    html_lines: list[str] = []
    in_list = False
    in_code = False
    in_blockquote = False

    for line in lines:
        stripped = line.strip()

        # Code blocks
        if stripped.startswith("```"):
            if in_code:
                html_lines.append("</pre>")
                in_code = False
            else:
                html_lines.append('<pre style="background:#f4f4f4;padding:12px;border-radius:6px;font-size:13px;overflow-x:auto;">')
                in_code = True
            continue
        if in_code:
            html_lines.append(line)
            continue

        # Close open lists if needed
        if in_list and not (stripped.startswith("- ") or stripped.startswith("* ") or re.match(r"^\d+\.\s", stripped)):
            html_lines.append("</ul>")
            in_list = False

        if in_blockquote and not stripped.startswith("> "):
            html_lines.append("</blockquote>")
            in_blockquote = False

        if not stripped:
            html_lines.append("<br/>")
            continue

        # Headers
        if stripped.startswith("#### "):
            html_lines.append(f'<h4 style="color:#333;margin:16px 0 8px;">{_inline(stripped[5:])}</h4>')
        elif stripped.startswith("### "):
            html_lines.append(f'<h3 style="color:#333;margin:18px 0 8px;">{_inline(stripped[4:])}</h3>')
        elif stripped.startswith("## "):
            html_lines.append(f'<h2 style="color:#222;margin:20px 0 10px;border-bottom:1px solid #eee;padding-bottom:6px;">{_inline(stripped[3:])}</h2>')
        elif stripped.startswith("# "):
            html_lines.append(f'<h1 style="color:#111;margin:24px 0 12px;">{_inline(stripped[2:])}</h1>')
        # Horizontal rule
        elif stripped in ("---", "***", "___"):
            html_lines.append('<hr style="border:none;border-top:1px solid #ddd;margin:16px 0;"/>')
        # Blockquote
        elif stripped.startswith("> "):
            if not in_blockquote:
                html_lines.append('<blockquote style="border-left:3px solid #ddd;padding-left:12px;margin:8px 0;color:#666;">')
                in_blockquote = True
            html_lines.append(f"<p>{_inline(stripped[2:])}</p>")
        # List items
        elif stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html_lines.append('<ul style="margin:8px 0;padding-left:20px;">')
                in_list = True
            html_lines.append(f"<li>{_inline(stripped[2:])}</li>")
        elif re.match(r"^\d+\.\s", stripped):
            text = re.sub(r"^\d+\.\s", "", stripped)
            if not in_list:
                html_lines.append('<ul style="margin:8px 0;padding-left:20px;">')
                in_list = True
            html_lines.append(f"<li>{_inline(text)}</li>")
        else:
            html_lines.append(f'<p style="margin:6px 0;line-height:1.6;">{_inline(stripped)}</p>')

    if in_list:
        html_lines.append("</ul>")
    if in_blockquote:
        html_lines.append("</blockquote>")
    if in_code:
        html_lines.append("</pre>")

    body_html = "\n".join(html_lines)
    return f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;max-width:680px;margin:0 auto;padding:20px;color:#333;font-size:15px;line-height:1.6;">
{body_html}
<hr style="border:none;border-top:1px solid #eee;margin-top:24px;"/>
<p style="font-size:11px;color:#999;">Sent by Orchid AI</p>
</body>
</html>"""


def _inline(text: str) -> str:
    """Convert inline markdown: bold, italic, links, code."""
    import re
    # Bold
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    # Italic
    text = re.sub(r"\*(.+?)\*", r"<em>\1</em>", text)
    # Links
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" style="color:#2563eb;">\1</a>', text)
    # Inline code
    text = re.sub(r"`(.+?)`", r'<code style="background:#f4f4f4;padding:1px 4px;border-radius:3px;font-size:13px;">\1</code>', text)
    return text


# ── OAuth token management ────────────────────────────────────────────────────

async def _get_valid_token() -> str | None:
    """Get a valid access token, refreshing if needed."""
    global _token_cache

    if not _token_cache:
        _token_cache = await _load_tokens_from_db()

    if not _token_cache.get("refresh_token"):
        return None

    # Check if access token is still valid
    if _token_cache.get("access_token") and _token_cache.get("expires_at", 0) > time.time() + 60:
        return _token_cache["access_token"]

    # Refresh
    from app.config import get_settings
    s = get_settings()

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(_TOKEN_URL, data={
            "client_id": s.gmail_client_id,
            "client_secret": s.gmail_client_secret,
            "refresh_token": _token_cache["refresh_token"],
            "grant_type": "refresh_token",
        })
        data = resp.json()

    if "access_token" not in data:
        logger.error("Gmail token refresh failed: %s", data)
        return None

    _token_cache["access_token"] = data["access_token"]
    _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
    await _save_tokens_to_db(_token_cache)

    return _token_cache["access_token"]


async def save_initial_tokens(code: str, redirect_uri: str) -> dict:
    """Exchange auth code for tokens (called by the OAuth callback endpoint)."""
    global _token_cache
    from app.config import get_settings
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

    _token_cache = {
        "access_token": data["access_token"],
        "refresh_token": data.get("refresh_token", ""),
        "expires_at": time.time() + data.get("expires_in", 3600),
    }
    await _save_tokens_to_db(_token_cache)
    return _token_cache


_TOKEN_FILE = Path(__file__).resolve().parent.parent.parent / "data" / ".gmail_tokens.json"


async def _load_tokens_from_db() -> dict:
    # Try DB first
    try:
        from app.db.session import AsyncSessionLocal
        from app.db.models.kv import KVStore

        async with AsyncSessionLocal() as db:
            kv = await db.get(KVStore, "gmail_tokens")
            if kv and kv.value:
                return json.loads(kv.value)
    except Exception:
        pass

    # Fallback: local file (survives DB wipes)
    if _TOKEN_FILE.exists():
        try:
            return json.loads(_TOKEN_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


async def _save_tokens_to_db(tokens: dict) -> None:
    # Save to DB
    try:
        from app.db.session import AsyncSessionLocal
        from app.db.models.kv import KVStore

        async with AsyncSessionLocal() as db:
            kv = await db.get(KVStore, "gmail_tokens")
            if kv:
                kv.value = json.dumps(tokens)
            else:
                db.add(KVStore(key="gmail_tokens", value=json.dumps(tokens)))
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to save Gmail tokens to DB: %s", exc)

    # Also save to local file as backup
    try:
        _TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TOKEN_FILE.write_text(json.dumps(tokens))
    except OSError as exc:
        logger.warning("Failed to save Gmail tokens to file: %s", exc)
