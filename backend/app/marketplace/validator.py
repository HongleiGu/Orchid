"""
Validates that an installed npm package conforms to the Orchid structure.

Valid structures:
  Skill:  SKILL.md at root + (execute.py | scripts/execute.py | index.py)
  Tool:   TOOL.md at root + (execute.py | scripts/execute.py | index.py)
  MCP:    mcp.json at root
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ValidationResult:
    valid: bool
    pkg_type: str | None  # "skill" | "tool" | "mcp" | None
    name: str
    description: str
    parameters: dict
    error: str | None = None


def validate_package(pkg_dir: Path) -> ValidationResult:
    """Check if a package directory is a valid Orchid package."""
    skill_md = pkg_dir / "SKILL.md"
    tool_md = pkg_dir / "TOOL.md"
    mcp_json = pkg_dir / "mcp.json"

    if skill_md.exists():
        return _validate_skill_or_tool(pkg_dir, skill_md, "skill")
    if tool_md.exists():
        return _validate_skill_or_tool(pkg_dir, tool_md, "tool")
    if mcp_json.exists():
        return _validate_mcp(pkg_dir, mcp_json)

    return ValidationResult(
        valid=False,
        pkg_type=None,
        name=pkg_dir.name,
        description="",
        parameters={},
        error="No SKILL.md, TOOL.md, or mcp.json found at package root",
    )


def _validate_skill_or_tool(pkg_dir: Path, md_path: Path, pkg_type: str) -> ValidationResult:
    # Check for execute entry point
    execute_candidates = [
        pkg_dir / "execute.py",
        pkg_dir / "scripts" / "execute.py",
        pkg_dir / "index.py",  # ClaWHub compat
    ]
    has_execute = any(c.exists() for c in execute_candidates)

    if not has_execute:
        return ValidationResult(
            valid=False,
            pkg_type=pkg_type,
            name=pkg_dir.name,
            description="",
            parameters={},
            error=f"Package has {md_path.name} but no execute.py, scripts/execute.py, or index.py",
        )

    meta = _parse_md(md_path)
    name = meta.get("name") or pkg_dir.name
    description = meta.get("description") or ""
    parameters = meta.get("parameters") or {"type": "object", "properties": {}, "required": []}

    return ValidationResult(
        valid=True,
        pkg_type=pkg_type,
        name=name,
        description=description,
        parameters=parameters,
    )


def _validate_mcp(pkg_dir: Path, mcp_path: Path) -> ValidationResult:
    import json

    try:
        config = json.loads(mcp_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        return ValidationResult(
            valid=False,
            pkg_type="mcp",
            name=pkg_dir.name,
            description="",
            parameters={},
            error=f"Invalid mcp.json: {exc}",
        )

    name = config.get("name") or pkg_dir.name
    description = config.get("description") or ""

    return ValidationResult(
        valid=True,
        pkg_type="mcp",
        name=name,
        description=description,
        parameters={},
    )


def _parse_md(path: Path) -> dict:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
            return yaml.safe_load("\n".join(lines[1:end])) or {}
        except (ValueError, yaml.YAMLError):
            pass
    return {}
