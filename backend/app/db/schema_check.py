"""Warn when the database schema is behind the code.

A stale database surfaces as `UndefinedColumn` deep inside an unrelated request,
which reads like an application bug — during development of the SSE endpoint it
cost real time before anyone thought to check the migration revision. Comparing
revisions at startup turns that into a message that names the actual problem.

Docker already runs `alembic upgrade head` in docker-entrypoint.sh before
uvicorn starts, so this mainly covers running the backend directly.
"""
from __future__ import annotations

import logging
import os

from sqlalchemy import inspect

logger = logging.getLogger(__name__)


def _head_revisions() -> set[str]:
    """Revision(s) alembic considers current, read from the migration scripts."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.abspath(os.path.join(here, "..", "..", ".."))
    ini = os.path.join(root, "alembic.ini")
    if not os.path.exists(ini):
        return set()

    cfg = Config(ini)
    cfg.set_main_option("script_location", os.path.join(root, "alembic"))
    return set(ScriptDirectory.from_config(cfg).get_heads())


def _applied_revision(connection) -> str | None:
    inspector = inspect(connection)
    if "alembic_version" not in inspector.get_table_names():
        return None
    row = connection.exec_driver_sql(
        "SELECT version_num FROM alembic_version"
    ).fetchone()
    return row[0] if row else None


async def warn_if_schema_is_stale(engine) -> None:
    """Log a warning when the applied revision is not at head. Never raises.

    Deliberately advisory rather than fatal: refusing to start would be the
    wrong call for someone poking at a scratch database, and the message is
    enough to stop the misdiagnosis this exists to prevent.
    """
    try:
        heads = _head_revisions()
        if not heads:
            return

        async with engine.connect() as conn:
            applied = await conn.run_sync(_applied_revision)

        if applied is None:
            logger.warning(
                "Database has no alembic_version table — no migrations have been "
                "applied. Run: alembic upgrade head"
            )
        elif applied not in heads:
            logger.warning(
                "Database schema is behind the code (applied=%s, head=%s). "
                "Expect confusing 'column does not exist' errors. "
                "Run: alembic upgrade head",
                applied, ", ".join(sorted(heads)),
            )
    except Exception as exc:  # pragma: no cover - diagnostics must never break startup
        logger.debug("Schema drift check skipped: %s", exc)
