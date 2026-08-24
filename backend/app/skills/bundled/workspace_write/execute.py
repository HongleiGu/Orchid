from __future__ import annotations

import pathlib

from skill_lib.vault import sanitize_name

WORKSPACE_ROOT = "/workspace"
MAX_CHARS = 400_000


async def execute(path: str, content: str, workspace: str = "default") -> str:
    if not path or not path.strip():
        return "Error: path is required."
    if content is None:
        content = ""
    if len(content) > MAX_CHARS:
        return f"Error: content too long ({len(content)} chars, max {MAX_CHARS})."

    rel = pathlib.PurePosixPath(path.strip().lstrip("/"))
    if not rel.parts or ".." in rel.parts:
        return "Error: path must be a relative path without '..'."

    ws = pathlib.Path(WORKSPACE_ROOT) / sanitize_name(workspace or "default")
    target = ws.joinpath(*rel.parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return f"Wrote {workspace}/{rel} ({len(content)} chars)."
