"""
Skill registry — loads skill folders at startup.

Each skill lives in its own directory:
    skills/builtin/my_skill/
        SKILL.md      ← YAML frontmatter: name, description, parameters
        execute.py    ← defines:  async def execute(**kwargs) -> str

SKILL.md format:
    ---
    name: my_skill
    description: One-line description shown to the LLM.
    parameters:
      type: object
      properties:
        param_a:
          type: string
          description: ...
      required:
        - param_a
    ---
"""
from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Awaitable, Callable

import yaml

logger = logging.getLogger(__name__)


@dataclass
class Skill:
    name: str
    description: str
    parameters: dict  # JSON Schema
    _execute: Callable[..., Awaitable[str]]

    @property
    def wire_name(self) -> str:
        from app.tools.base import sanitize_tool_name
        return sanitize_tool_name(self.name)

    async def execute(self, **kwargs) -> str:
        return await self._execute(**kwargs)

    def to_openai_spec(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.wire_name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def to_anthropic_spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.parameters,
        }


class SkillRegistry:
    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    def register(self, skill: Skill) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> Skill:
        if name not in self._skills:
            raise KeyError(f"Skill not found: {name!r}")
        return self._skills[name]

    def resolve(self, names: list[str]) -> list[Skill]:
        missing = [n for n in names if n not in self._skills]
        if missing:
            raise KeyError(f"Unknown skills: {missing}")
        return [self._skills[n] for n in names]

    def all(self) -> list[Skill]:
        return list(self._skills.values())

    def names(self) -> list[str]:
        return list(self._skills.keys())

    def load_from_dir(self, directory: Path, prefix: str = "") -> None:
        """Scan a directory and load every valid skill subfolder."""
        if not directory.exists():
            return
        for skill_dir in sorted(directory.iterdir()):
            if not skill_dir.is_dir():
                continue
            md_path = skill_dir / "SKILL.md"
            py_path = skill_dir / "execute.py"
            if not md_path.exists() or not py_path.exists():
                continue
            try:
                skill = _load_skill(skill_dir, md_path, py_path)
                if prefix:
                    skill.name = f"{prefix}{skill.name}"
                self.register(skill)
                logger.debug("Loaded skill %r from %s", skill.name, skill_dir)
            except Exception:
                logger.warning("Failed to load skill from %s", skill_dir, exc_info=True)


def _parse_skill_md(path: Path) -> dict:
    """Extract YAML frontmatter between --- delimiters."""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        try:
            end = lines.index("---", 1)
            return yaml.safe_load("\n".join(lines[1:end])) or {}
        except (ValueError, yaml.YAMLError):
            pass
    return {}


def _load_skill(skill_dir: Path, md_path: Path, py_path: Path) -> Skill:
    meta = _parse_skill_md(md_path)
    name = meta.get("name") or skill_dir.name
    description = meta.get("description") or name
    parameters = meta.get("parameters") or {
        "type": "object",
        "properties": {},
        "required": [],
    }

    module_name = f"_skill_{skill_dir.name}"
    spec = importlib.util.spec_from_file_location(module_name, py_path)
    module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
    sys.modules[module_name] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]

    execute_fn: Callable = getattr(module, "execute")
    return Skill(name=name, description=description, parameters=parameters, _execute=execute_fn)


# Module-level singleton
skill_registry = SkillRegistry()
