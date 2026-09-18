"""Who owns which vault project (OR-48).

The vault is a shared directory written from two places that know different
things about the user:

  auto-save        backend, in the run task — knows the run's user directly.
  vault_write      the skill-runner container — knows nothing about the user.

To attribute the second, the run's user is put on a context variable when the
run starts (the same pattern spans use), and the RemoteSkill proxy — which does
run in the backend — records ownership after a vault-writing skill succeeds.

Ownership is claimed first-write-wins: the first user to create a project owns
it, and later writes never reassign it. The recorded string must equal the
on-disk directory name, so the two sanitisers here mirror, exactly, the ones the
writers use — see the comments on each. A drift there would misfile ownership
and hide a user's own outputs from them, so both are pinned by tests.
"""
from __future__ import annotations

import contextvars
import logging
import re

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.vault_owner import VaultOwner

logger = logging.getLogger(__name__)

# The current run's user, for skill writes that cross into the skill-runner and
# come back. None for an operator (static-key) run — those stay unowned.
current_run_user: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "orchid_run_user", default=None,
)

# Skills that write to the vault. Kept explicit rather than inferred: there is
# one today, and a wrong guess here would silently fail to attribute a file.
VAULT_WRITING_SKILLS: frozenset[str] = frozenset({"@orchid/vault_write"})


def sanitize_skill_project(name: str) -> str:
    """Mirror of skill_lib.vault.sanitize_name (skill-runner), which turns the
    vault_write `project` argument into its directory name. Kept in lockstep by
    test_vault_ownership; copied rather than imported because it lives in the
    other service."""
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    name = re.sub(r"[^\w\-. ]", "", name).strip()
    return name or "untitled"


def sanitize_autosave_project(task_name: str) -> str:
    """Mirror of _auto_save_to_vault in run_executor.py, which derives a project
    from the task name."""
    return re.sub(r"[^\w\-. ]", "", task_name).strip().lower().replace(" ", "-") or "runs"


# ── session-level operations ──────────────────────────────────────────────────

async def claim(db: AsyncSession, project: str, user_id: str | None) -> None:
    """Record ownership, first-write-wins. No-op for an operator run (no user).
    Does not commit — the caller owns the transaction."""
    if not user_id or not project:
        return
    await db.execute(
        pg_insert(VaultOwner)
        .values(project=project, user_id=user_id)
        .on_conflict_do_nothing(index_elements=["project"])
    )


async def owned_projects(db: AsyncSession, user_id: str) -> set[str]:
    rows = await db.execute(select(VaultOwner.project).where(VaultOwner.user_id == user_id))
    return set(rows.scalars().all())


async def is_owner(db: AsyncSession, project: str, user_id: str) -> bool:
    row = await db.get(VaultOwner, project)
    return row is not None and row.user_id == user_id


# ── convenience wrappers that open their own session (for the API) ────────────

async def owned_projects_for(user_id: str) -> set[str]:
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        return await owned_projects(db, user_id)


async def can_view(project: str, user_id: str) -> bool:
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        return await is_owner(db, project, user_id)


async def note_vault_write(skill_name: str, kwargs: dict) -> None:
    """Called by the RemoteSkill proxy after a skill succeeds. Records ownership
    when it was a vault write made inside a run with a known user. Best-effort:
    a failure here must never break the skill call that already succeeded."""
    if skill_name not in VAULT_WRITING_SKILLS:
        return
    user_id = current_run_user.get()
    project = kwargs.get("project")
    if not user_id or not isinstance(project, str) or not project:
        return
    try:
        from app.db.session import AsyncSessionLocal
        async with AsyncSessionLocal() as db:
            await claim(db, sanitize_skill_project(project), user_id)
            await db.commit()
    except Exception as exc:
        logger.warning("Could not record vault ownership for %r: %s", project, exc)
