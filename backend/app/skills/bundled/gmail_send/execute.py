from __future__ import annotations

import base64
import logging
import mimetypes
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import httpx

from skill_lib.gmail_auth import get_valid_token
from skill_lib.markdown import looks_like_markdown, to_html
from skill_lib.vault import resolve_vault_path

logger = logging.getLogger(__name__)

_GMAIL_API = "https://gmail.googleapis.com/gmail/v1"


async def execute(
    to: str,
    subject: str,
    body: str,
    html: bool = False,
    cc: str = "",
    attachments: str = "",
) -> str:
    try:
        token = await get_valid_token()
        if not token:
            return "Error: Gmail not authorized. Visit /api/v1/gmail/auth to set up."

        attachment_paths = _resolve_attachments(attachments)
        msg = _build_message(to, subject, body, html, cc, attachment_paths)
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


def _build_message(to, subject, body, is_html, cc, attachments):
    body_part = MIMEMultipart("alternative")
    if is_html:
        body_part.attach(MIMEText(body, "plain"))
        body_part.attach(MIMEText(body, "html"))
    elif looks_like_markdown(body):
        body_part.attach(MIMEText(body, "plain"))
        body_part.attach(MIMEText(to_html(body, style="email"), "html"))
    else:
        body_part.attach(MIMEText(body, "plain"))

    if not attachments:
        body_part["To"] = to
        body_part["Subject"] = subject
        if cc:
            body_part["Cc"] = cc
        return body_part

    outer = MIMEMultipart("mixed")
    outer["To"] = to
    outer["Subject"] = subject
    if cc:
        outer["Cc"] = cc
    outer.attach(body_part)
    for path in attachments:
        outer.attach(_build_attachment(path))
    return outer


def _build_attachment(path: Path) -> MIMEBase:
    mime_type, _ = mimetypes.guess_type(path.name)
    if mime_type:
        maintype, subtype = mime_type.split("/", 1)
    else:
        maintype, subtype = "application", "octet-stream"
    part = MIMEBase(maintype, subtype)
    part.set_payload(path.read_bytes())
    encoders.encode_base64(part)
    part.add_header("Content-Disposition", f'attachment; filename="{path.name}"')
    return part


def _resolve_attachments(spec: str) -> list[Path]:
    out: list[Path] = []
    for raw in (spec or "").split(","):
        raw = raw.strip()
        if not raw:
            continue
        p = resolve_vault_path(raw)
        if p:
            out.append(p)
    return out
