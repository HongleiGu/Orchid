from __future__ import annotations

import pathlib

from skill_lib.vault import sanitize_name

WORKSPACE_ROOT = "/workspace"
MAX_CHARS = 32_000


async def execute(path: str, workspace: str = "default") -> str:
    ws = pathlib.Path(WORKSPACE_ROOT) / sanitize_name(workspace or "default")
    rel = pathlib.PurePosixPath((path or "").strip().lstrip("/"))
    if not rel.parts or ".." in rel.parts:
        return "Error: path must be a relative path without '..'."

    target = ws.joinpath(*rel.parts)
    if not target.exists() or not target.is_file():
        listing = ""
        if ws.exists():
            listing = "\n".join(
                sorted(str(p.relative_to(ws)) for p in ws.glob("**/*") if p.is_file())
            )
        return f"Not found: {workspace}/{rel}\nFiles in workspace:\n{listing or '<empty>'}"

    text = target.read_text(encoding="utf-8", errors="replace")
    if len(text) > MAX_CHARS:
        return text[:MAX_CHARS] + f"\n... [truncated at {MAX_CHARS} chars]"
    return text
