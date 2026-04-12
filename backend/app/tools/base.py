from __future__ import annotations

import re
from abc import ABC, abstractmethod


def sanitize_tool_name(name: str) -> str:
    """Convert a namespaced name to an LLM-safe identifier.
    '@orchid/web_search' → 'orchid__web_search'
    '@author/skill-foo' → 'author__skill-foo'
    """
    return re.sub(r"[^a-zA-Z0-9_-]", "_", name).strip("_")


class BaseTool(ABC):
    name: str
    description: str
    parameters: dict  # JSON Schema object

    @property
    def wire_name(self) -> str:
        """LLM-safe name used in tool specs and tool_call responses."""
        return sanitize_tool_name(self.name)

    @abstractmethod
    async def call(self, **kwargs) -> str: ...

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
