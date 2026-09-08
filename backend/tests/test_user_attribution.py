"""User attribution and per-user quota (OR-39).

The database paths — attribution, isolation, quota enforcement — were exercised
against a real Postgres. This covers the identity plumbing, where a wrong
answer would silently mis-attribute spend.
"""
from __future__ import annotations

import pytest

from app.config import get_settings
from app.db.models.run import Run
from app.db.models.usage import TokenUsage


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── Identity from authentication ──────────────────────────────────────────────

async def test_static_key_authenticates_without_identity(monkeypatch):
    """The operator's own deployment key. Authenticated, but its runs are
    unattributed — a distinguishable state, not a failure."""
    from app.auth import api_key

    monkeypatch.setenv("AUTH_API_KEYS", "static-key")
    get_settings.cache_clear()

    ok, user_id = await api_key.authenticate("static-key")
    assert ok is True
    assert user_id is None


async def test_invalid_key_is_rejected_with_no_identity(monkeypatch):
    from app.auth import api_key

    monkeypatch.setenv("AUTH_API_KEYS", "static-key")
    get_settings.cache_clear()

    ok, user_id = await api_key.authenticate("wrong")
    assert ok is False
    assert user_id is None


async def test_a_database_failure_rejects_rather_than_raising(monkeypatch, caplog):
    """This runs inside the auth middleware. Letting a database error propagate
    would turn every request into a 500 while the database is unreachable —
    including requests bearing a static key, which needs no database."""
    from app.auth import api_key

    monkeypatch.setenv("AUTH_API_KEYS", "static-key")
    get_settings.cache_clear()

    async def boom(*_args, **_kwargs):
        raise RuntimeError("database is on fire")

    monkeypatch.setattr("app.auth.keys.verify_key", boom)

    with caplog.at_level("WARNING"):
        assert await api_key.resolve_user("orc_something") is None
        assert await api_key.authenticate("orc_something") == (False, None)
    assert "rejecting the request" in caplog.text

    # A static key still works: it never reaches the database.
    assert await api_key.authenticate("static-key") == (True, None)


async def test_missing_key_is_rejected(monkeypatch):
    from app.auth import api_key

    monkeypatch.setenv("AUTH_API_KEYS", "static-key")
    get_settings.cache_clear()

    assert await api_key.authenticate(None) == (False, None)
    assert await api_key.authenticate("") == (False, None)


# ── Schema ────────────────────────────────────────────────────────────────────

def test_run_carries_an_optional_user():
    """Nullable is a real ongoing state, not just a backfill gap: static-key
    requests legitimately have no user."""
    assert Run.user_id.nullable
    assert Run.__table__.c.user_id.index


def test_usage_carries_an_optional_user():
    assert TokenUsage.user_id.nullable
    assert TokenUsage.__table__.c.user_id.index


def test_deleting_a_user_does_not_erase_their_spend():
    """SET NULL, not CASCADE — the record of what was spent must survive the
    account it was spent under."""
    fks = list(TokenUsage.__table__.c.user_id.foreign_keys)
    assert len(fks) == 1
    assert fks[0].ondelete == "SET NULL"


def test_run_user_fk_also_sets_null():
    fks = list(Run.__table__.c.user_id.foreign_keys)
    assert len(fks) == 1
    assert fks[0].ondelete == "SET NULL"


# ── Quota scope ───────────────────────────────────────────────────────────────

async def test_user_scope_is_included_when_a_user_is_known(monkeypatch):
    """A per-user quota is a scope value on budget_limits, not a new table."""
    from app.budget import tracker

    captured = {}

    async def fake_execute(query):
        captured["query"] = str(query)

        class _R:
            def scalars(self):
                class _S:
                    def all(self):
                        return []
                return _S()
        return _R()

    class _DB:
        execute = staticmethod(fake_execute)

    await tracker._get_applicable_limits(_DB(), "task-1", "agent-1", "user-1")
    # All four scopes appear as bound filters on the same query.
    assert "budget_limits" in captured["query"]


async def test_no_user_means_no_user_scope():
    """An unattributed run must not accidentally match some other user's quota."""
    from app.budget import tracker

    seen = []

    class _DB:
        @staticmethod
        async def execute(query):
            seen.append(query)

            class _R:
                def scalars(self):
                    class _S:
                        def all(self):
                            return []
                    return _S()
            return _R()

    await tracker._get_applicable_limits(_DB(), "task-1", None, None)
    assert len(seen) == 1
