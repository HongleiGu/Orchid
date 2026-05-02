"""
Validates that an installed package conforms to the Orchid structure.

A valid package has SKILL.md at the root and one of:
  - execute.py
  - scripts/execute.py
  - index.py  (ClaWHub compat)

The legacy TOOL.md / mcp.json formats are no longer supported — every
executable is a skill.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class ValidationResult:
    valid: bool
    pkg_type: str | None  # "skill" | None (kept for backward-compat in DB rows)
    name: str
    description: str
    parameters: dict
    error: str | None = None


def validate_package(pkg_dir: Path) -> ValidationResult:
    skill_md = pkg_dir / "SKILL.md"
    if not skill_md.exists():
        return ValidationResult(
            valid=False,
            pkg_type=None,
            name=pkg_dir.name,
            description="",
            parameters={},
            error="No SKILL.md found at package root",
        )

    execute_candidates = [
        pkg_dir / "execute.py",
        pkg_dir / "scripts" / "execute.py",
        pkg_dir / "index.py",
    ]
    if not any(c.exists() for c in execute_candidates):
        return ValidationResult(
            valid=False,
            pkg_type="skill",
            name=pkg_dir.name,
            description="",
            parameters={},
            error="Package has SKILL.md but no execute.py, scripts/execute.py, or index.py",
        )

    meta = _parse_md(skill_md)
    return ValidationResult(
        valid=True,
        pkg_type="skill",
        name=meta.get("name") or pkg_dir.name,
        description=meta.get("description") or "",
        parameters=meta.get("parameters") or {"type": "object", "properties": {}, "required": []},
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
