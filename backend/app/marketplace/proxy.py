"""
RemoteSkill — proxy that forwards `.execute()` calls to the skill-runner.

name        = registry key (e.g. "@orchid/vault_write" or "@author/skill-foo")
runner_name = the name skill-runner knows it by (from SKILL.md `name:` field)
"""
from __future__ import annotations

import httpx

from app.skills.registry import Skill

SKILL_RUNNER_URL = "http://skill-runner:9000"
# Hard ceiling above skill-runner's MAX_EXECUTE_TIMEOUT so we don't drop a
# legitimately long-running skill before it can return.
EXECUTE_TIMEOUT = 605


class RemoteSkill(Skill):
    """A skill (bundled or marketplace) that executes in the skill-runner."""

    def __init__(self, name: str, description: str, parameters: dict,
                 runner_name: str | None = None) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters
        self._runner_name = runner_name or name
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
