from __future__ import annotations

from skill_lib.vault import sanitize_name, vault_dir


async def execute(project: str, filename: str = "") -> str:
    try:
        project = sanitize_name(project)
        project_dir = vault_dir() / project

        if not project_dir.exists():
            return f"Project '{project}' not found in vault."

        if not filename:
            files = sorted(f.name for f in project_dir.glob("*.md"))
            if not files:
                return f"No documents in vault project '{project}'."
            return f"Documents in '{project}' ({len(files)}):\n" + "\n".join(f"  - {f}" for f in files)

        filename = sanitize_name(filename)
        if not filename.endswith(".md"):
            filename += ".md"

        file_path = project_dir / filename
        if not file_path.exists():
            return f"File not found: {project}/{filename}"
        return file_path.read_text(encoding="utf-8")
    except Exception as exc:
        return f"Vault read failed: {exc}"
