"""
File-based shared state between backend and skill-runner.

Backend writes credentials/cached IDs to STATE_DIR; the runner reads from the
same files. STATE_DIR is bind-mounted in docker-compose so both processes see
the same filesystem location.
"""
from __future__ import annotations

import json
import os
from pathlib import Path


def state_dir() -> Path:
    p = Path(os.environ.get("STATE_DIR", "/state"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def load_json(name: str) -> dict:
    """Load a JSON state file. Returns {} if missing or unreadable."""
    path = state_dir() / name
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def save_json(name: str, data: dict) -> None:
    path = state_dir() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
