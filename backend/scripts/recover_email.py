"""Decode a raw RFC 822 email (multipart/alternative) and write its text/plain
body to the Orchid vault as a markdown file.

Usage:
    python backend/scripts/recover_email.py <raw_email_file> <vault_project> <filename>

Example:
    python backend/scripts/recover_email.py /tmp/report.eml professor-research-pipeline Marek-Rei

The raw file can be either:
  - the "Show original" output from Gmail (headers + body), or
  - just the MIME part (no outer SMTP envelope).

The script walks the MIME tree, picks the first text/plain part, decodes
base64/quoted-printable, and writes it to vault/<project>/<filename>.md.
"""
from __future__ import annotations

import email
import sys
from email.message import Message
from pathlib import Path


def extract_plain(msg: Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            if part.get_content_type() == "text/plain":
                payload = part.get_payload(decode=True)
                if payload:
                    charset = part.get_content_charset() or "utf-8"
                    return payload.decode(charset, errors="replace")
        return ""
    payload = msg.get_payload(decode=True)
    if not payload:
        return ""
    charset = msg.get_content_charset() or "utf-8"
    return payload.decode(charset, errors="replace")


def main() -> int:
    if len(sys.argv) != 4:
        print(__doc__)
        return 2
    src = Path(sys.argv[1])
    project = sys.argv[2]
    name = sys.argv[3]
    if not name.endswith(".md"):
        name += ".md"

    raw = src.read_bytes()
    msg = email.message_from_bytes(raw)
    text = extract_plain(msg)
    if not text.strip():
        print(f"ERROR: no text/plain body in {src}")
        return 1

    # Find the vault dir — repo root is two dirs up from this file
    repo_root = Path(__file__).resolve().parents[2]
    vault_dir = repo_root / "vault" / project
    vault_dir.mkdir(parents=True, exist_ok=True)
    out = vault_dir / name
    out.write_text(text, encoding="utf-8")
    print(f"Recovered {len(text)} chars → {out.relative_to(repo_root)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
