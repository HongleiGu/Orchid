from __future__ import annotations

import os
import re
from pathlib import Path


def vault_dir() -> Path:
    return Path(os.environ.get("VAULT_DIR", "/vault"))


def sanitize_name(name: str) -> str:
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    name = re.sub(r"[^\w\-. ]", "", name).strip()
    return name or "untitled"


def resolve_vault_path(raw: str) -> Path | None:
    """Resolve a vault-relative or absolute path. Tolerates a `vault://` prefix.
    Returns None if the file doesn't exist."""
    raw = raw.strip()
    if raw.startswith("vault://"):
        raw = raw[len("vault://"):]
    raw = raw.lstrip("/")
    p = Path(raw)
    if not p.is_absolute():
        p = vault_dir() / raw
    return p if p.exists() and p.is_file() else None
