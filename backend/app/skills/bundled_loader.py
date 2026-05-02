"""
Auto-loads bundled skills from backend/app/skills/bundled/ and registers
RemoteSkill proxies in the agent framework. The same directory is bind-mounted
into skill-runner so every registered proxy has a corresponding loaded skill
on the runner side.

Bundled skills use the @orchid/ namespace and are always available — no
marketplace install needed.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.marketplace.proxy import RemoteSkill
from app.marketplace.validator import validate_package
from app.skills.registry import skill_registry

logger = logging.getLogger(__name__)

BUNDLED_DIR = Path(__file__).parent / "bundled"
_NAMESPACE = "@orchid/"


def register_bundled_skills() -> int:
    """Scan bundled/ dir and register each valid skill as a RemoteSkill proxy.
    Returns the number of skills registered."""
    if not BUNDLED_DIR.exists():
        return 0

    count = 0
    for skill_dir in sorted(BUNDLED_DIR.iterdir()):
        if not skill_dir.is_dir():
            continue

        validation = validate_package(skill_dir)
        if not validation.valid:
            logger.debug("Skipping bundled dir %s: %s", skill_dir.name, validation.error)
            continue

        registry_name = f"{_NAMESPACE}{skill_dir.name}"
        proxy = RemoteSkill(
            name=registry_name,
            description=validation.description,
            parameters=validation.parameters,
            runner_name=validation.name,
        )
        skill_registry.register(proxy)
        logger.info("Registered bundled skill %r → runner:%r", registry_name, validation.name)
        count += 1

    return count
