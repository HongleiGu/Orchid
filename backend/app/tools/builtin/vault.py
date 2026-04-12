"""
Vault tools — read/write markdown files to the shared vault directory.

The vault is an Obsidian-compatible folder of .md files organized by project.
Structure:
  vault/
  ├── <project>/
  │   ├── <document>.md
  │   └── assets/
  │       └── <file>
  └── .orchid/
      └── index.json   ← auto-maintained metadata index
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

# In Docker: /app/vault (backend) or /vault (skill-runner)
# Local dev: project_root/vault
VAULT_DIR = Path(os.environ.get("VAULT_DIR", "/app/vault"))
INDEX_PATH = VAULT_DIR / ".orchid" / "index.json"


class VaultWriteTool(BaseTool):
    name = "@orchid/vault_write"
    description = (
        "Save a markdown document to the vault. Organizes by project folder. "
        "Use for persisting pipeline outputs, research reports, digests, etc."
    )
    parameters = {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Project/folder name (e.g. 'daily-digests', 'professor-reports').",
            },
            "filename": {
                "type": "string",
                "description": "Filename without extension (e.g. '2026-04-10-ai-digest'). .md is added automatically.",
            },
            "content": {
                "type": "string",
                "description": "Markdown content to save.",
            },
            "tags": {
                "type": "string",
                "default": "",
                "description": "Comma-separated tags for indexing (e.g. 'ai,research,digest').",
            },
        },
        "required": ["project", "filename", "content"],
    }

    async def call(
        self,
        project: str,
        filename: str,
        content: str,
        tags: str = "",
    ) -> str:
        try:
            # Sanitize path components
            project = _sanitize(project)
            filename = _sanitize(filename)
            if not filename.endswith(".md"):
                filename += ".md"

            # Create project dir
            project_dir = VAULT_DIR / project
            project_dir.mkdir(parents=True, exist_ok=True)
            (project_dir / "assets").mkdir(exist_ok=True)

            # Write file
            file_path = project_dir / filename
            file_path.write_text(content, encoding="utf-8")

            # Update index
            _update_index(project, filename, tags, len(content))

            rel_path = f"{project}/{filename}"
            return f"Saved to vault: {rel_path} ({len(content)} chars)"
        except Exception as exc:
            logger.error("Vault write failed: %s", exc)
            return f"Vault write failed: {exc}"


class VaultReadTool(BaseTool):
    name = "@orchid/vault_read"
    description = (
        "Read a markdown document from the vault. "
        "Can read a specific file or list files in a project."
    )
    parameters = {
        "type": "object",
        "properties": {
            "project": {
                "type": "string",
                "description": "Project/folder name.",
            },
            "filename": {
                "type": "string",
                "default": "",
                "description": "Specific file to read. Empty = list all files in project.",
            },
        },
        "required": ["project"],
    }

    async def call(self, project: str, filename: str = "") -> str:
        try:
            project = _sanitize(project)
            project_dir = VAULT_DIR / project

            if not project_dir.exists():
                return f"Project '{project}' not found in vault."

            if not filename:
                # List files
                files = sorted(f.name for f in project_dir.glob("*.md"))
                if not files:
                    return f"No documents in vault project '{project}'."
                return f"Documents in '{project}' ({len(files)}):\n" + "\n".join(f"  - {f}" for f in files)

            filename = _sanitize(filename)
            if not filename.endswith(".md"):
                filename += ".md"

            file_path = project_dir / filename
            if not file_path.exists():
                return f"File not found: {project}/{filename}"

            content = file_path.read_text(encoding="utf-8")
            return content
        except Exception as exc:
            logger.error("Vault read failed: %s", exc)
            return f"Vault read failed: {exc}"


class VaultSearchTool(BaseTool):
    name = "@orchid/vault_search"
    description = (
        "Search the vault for documents by keyword. "
        "Searches file names and content across all projects."
    )
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search keyword.",
            },
            "project": {
                "type": "string",
                "default": "",
                "description": "Limit search to a specific project. Empty = search all.",
            },
            "max_results": {
                "type": "integer",
                "default": 10,
            },
        },
        "required": ["query"],
    }

    async def call(self, query: str, project: str = "", max_results: int = 10) -> str:
        try:
            query_lower = query.lower()
            results: list[dict] = []

            search_dirs = []
            if project:
                p = VAULT_DIR / _sanitize(project)
                if p.exists():
                    search_dirs.append(p)
            else:
                search_dirs = [d for d in VAULT_DIR.iterdir()
                               if d.is_dir() and d.name != ".orchid"]

            for proj_dir in search_dirs:
                for md_file in proj_dir.glob("*.md"):
                    content = md_file.read_text(encoding="utf-8")
                    # Check filename and content
                    if query_lower in md_file.stem.lower() or query_lower in content.lower():
                        # Find matching snippet
                        idx = content.lower().find(query_lower)
                        snippet = ""
                        if idx >= 0:
                            start = max(0, idx - 50)
                            end = min(len(content), idx + len(query) + 100)
                            snippet = content[start:end].replace("\n", " ")
                        results.append({
                            "path": f"{proj_dir.name}/{md_file.name}",
                            "snippet": snippet,
                        })
                    if len(results) >= max_results:
                        break

            if not results:
                return f"No vault documents matching '{query}'."

            lines = [f"Found {len(results)} documents matching '{query}':\n"]
            for r in results:
                lines.append(f"- **{r['path']}**")
                if r["snippet"]:
                    lines.append(f"  ...{r['snippet']}...")
            return "\n".join(lines)
        except Exception as exc:
            return f"Vault search failed: {exc}"


# ── Helpers ──────────────────────────────────────────────────────────────────

def _sanitize(name: str) -> str:
    """Remove path traversal and invalid chars."""
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    name = re.sub(r"[^\w\-. ]", "", name).strip()
    return name or "untitled"


def _update_index(project: str, filename: str, tags: str, size: int) -> None:
    """Maintain a simple JSON index for future RAG."""
    try:
        INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
        index: dict = {}
        if INDEX_PATH.exists():
            index = json.loads(INDEX_PATH.read_text())

        key = f"{project}/{filename}"
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
        index[key] = {
            "project": project,
            "filename": filename,
            "tags": tag_list,
            "size": size,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        INDEX_PATH.write_text(json.dumps(index, indent=2))
    except Exception as exc:
        logger.warning("Failed to update vault index: %s", exc)
