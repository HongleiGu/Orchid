from __future__ import annotations

import json
from datetime import datetime, timezone

from skill_lib.vault import sanitize_name, vault_dir


async def execute(project: str, filename: str, content: str, tags: str = "") -> str:
    try:
        project = sanitize_name(project)
        filename = sanitize_name(filename)
        if not filename.endswith(".md"):
            filename += ".md"

        vd = vault_dir()
        project_dir = vd / project
        project_dir.mkdir(parents=True, exist_ok=True)
        (project_dir / "assets").mkdir(exist_ok=True)

        file_path = project_dir / filename
        file_path.write_text(content, encoding="utf-8")

        _update_index(vd, project, filename, tags, len(content))

        return f"Saved to vault: {project}/{filename} ({len(content)} chars)"
    except Exception as exc:
        return f"Vault write failed: {exc}"


def _update_index(vd, project: str, filename: str, tags: str, size: int) -> None:
    try:
        index_path = vd / ".orchid" / "index.json"
        index_path.parent.mkdir(parents=True, exist_ok=True)
        index: dict = {}
        if index_path.exists():
            index = json.loads(index_path.read_text(encoding="utf-8"))

        key = f"{project}/{filename}"
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        index[key] = {
            "project": project,
            "filename": filename,
            "tags": tag_list,
            "size": size,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        index_path.write_text(json.dumps(index, indent=2), encoding="utf-8")
    except Exception:
        pass  # index is best-effort
