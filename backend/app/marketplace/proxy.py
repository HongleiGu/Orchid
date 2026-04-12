"""
RemoteSkill / RemoteTool — wrappers that execute in the skill-runner container
but present the same interface as local BaseTool/Skill to the agent framework.

name        = registry key (npm_name, e.g. "orchid-skill-weather")
runner_name = the name skill-runner knows it by (from SKILL.md, e.g. "weather")
"""
from __future__ import annotations

import httpx

from app.skills.registry import Skill
from app.tools.base import BaseTool

SKILL_RUNNER_URL = "http://skill-runner:9000"
EXECUTE_TIMEOUT = 35  # slightly above skill-runner's 30s timeout


class RemoteSkill(Skill):
    """A marketplace skill that executes in the sandboxed skill-runner."""

    def __init__(self, name: str, description: str, parameters: dict,
                 runner_name: str | None = None) -> None:
        self.name = name                          # registry key (npm_name)
        self.description = description
        self.parameters = parameters
        self._runner_name = runner_name or name   # name skill-runner uses
        self._execute = self._remote_execute

    async def execute(self, **kwargs) -> str:
        return await self._remote_execute(**kwargs)

    async def _remote_execute(self, **kwargs) -> str:
        async with httpx.AsyncClient(timeout=EXECUTE_TIMEOUT) as client:
            resp = await client.post(
                f"{SKILL_RUNNER_URL}/execute",
                json={"skill_name": self._runner_name, "kwargs": kwargs},
            )
        data = resp.json()
        if data.get("error"):
            return f"Error: {data['error']}"
        return data.get("result", "")


class RemoteTool(BaseTool):
    """A marketplace tool that executes in the sandboxed skill-runner."""

    def __init__(self, name: str, description: str, parameters: dict,
                 runner_name: str | None = None) -> None:
        self.name = name                          # registry key (npm_name)
        self.description = description
        self.parameters = parameters
        self._runner_name = runner_name or name   # name skill-runner uses

    async def call(self, **kwargs) -> str:
        async with httpx.AsyncClient(timeout=EXECUTE_TIMEOUT) as client:
            resp = await client.post(
                f"{SKILL_RUNNER_URL}/execute",
                json={"skill_name": self._runner_name, "kwargs": kwargs},
            )
        data = resp.json()
        if data.get("error"):
            return f"Error: {data['error']}"
        return data.get("result", "")
