"""
Skill registry — the only execution-surface abstraction the agent sees.

Every skill is a remote skill: it lives in skill-runner (either as a bundled
package shipped with Orchid or a marketplace package installed via npm). The
registry holds RemoteSkill proxies; this module also defines the Skill base
class that those proxies inherit from.

There are no local in-process skills. The previous load_from_dir path that
loaded `app/skills/builtin/<name>/execute.py` directly into the backend
process has been removed — it muddied the security boundary and meant two
ways to ship a skill.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)


def sanitize_skill_name(name: str) -> str:
    """Convert a namespaced name to an LLM-safe identifier.
    '@orchid/vault_write' → 'orchid__vault_write'
    '@author/skill-foo'   → 'author__skill-foo'
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_")


@dataclass
class Skill:
    name: str
    description: str
    parameters: dict  # JSON Schema
    _execute: Callable[..., Awaitable[str]]

    @property
    def wire_name(self) -> str:
        return sanitize_skill_name(self.name)

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
            "name": self.wire_name,
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

    def deregister(self, name: str) -> bool:
        return self._skills.pop(name, None) is not None


# Module-level singleton
skill_registry = SkillRegistry()
