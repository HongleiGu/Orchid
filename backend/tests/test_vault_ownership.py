"""Vault project ownership (OR-48).

The sanitiser mirrors are pinned here: the string recorded as an owner must
equal the on-disk directory name, or a user's own outputs would be hidden from
them. The filtering is unit-tested with the ownership lookups stubbed; the
database claim/first-write-wins paths are exercised against real Postgres in the
verification script.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1 import vault as vault_module
from app.vault import ownership


# ── sanitiser mirrors (must match the writers) ────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("Market Brief", "Market Brief"),      # skill sanitiser keeps case and spaces
    ("../etc", "etc"),
    (r"a/b\c", "abc"),
    ("研究 2026", "研究 2026"),
    ("", "untitled"),
    ("!!!", "untitled"),
])
def test_skill_sanitiser_matches_skill_lib(raw, expected):
    assert ownership.sanitize_skill_project(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("China Market & News Daily Brief", "china-market--news-daily-brief"),
    ("Market Brief", "market-brief"),
    ("", "runs"),
])
def test_autosave_sanitiser_matches_executor(raw, expected):
    # Mirrors run_executor._auto_save_to_vault exactly, incl. the "runs" fallback.
    assert ownership.sanitize_autosave_project(raw) == expected


def test_operator_writes_are_not_claimed():
    """A run with no user (static key) creates no ownership row — so the project
    stays unowned and visible only to an operator."""
    calls = []

    class _Db:
        async def execute(self, *a, **k): calls.append(a)
    import asyncio
    asyncio.run(ownership.claim(_Db(), "market-brief", None))
    assert calls == []


# ── API filtering ─────────────────────────────────────────────────────────────

@pytest.fixture
def vault(tmp_path, monkeypatch):
    root = tmp_path / "vault"
    for proj in ("alice-brief", "bob-brief", "legacy"):
        (root / proj).mkdir(parents=True)
        (root / proj / "out.md").write_text(f"# {proj}", encoding="utf-8")
    monkeypatch.setattr(vault_module, "VAULT_DIR", root)
    return root


def client_as(viewer, owned):
    """A test app whose middleware sets a viewer, with ownership stubbed."""
    async def owned_projects_for(user_id):
        return set(owned) if user_id == viewer else set()

    async def can_view(project, user_id):
        return user_id == viewer and project in owned

    import app.vault.ownership as own
    app = FastAPI()

    @app.middleware("http")
    async def set_viewer(request, call_next):
        request.state.user_id = viewer
        return await call_next(request)

    app.include_router(vault_module.router, prefix="/api/v1")
    import pytest as _p
    mp = _p.MonkeyPatch()
    mp.setattr(own, "owned_projects_for", owned_projects_for)
    mp.setattr(own, "can_view", can_view)
    return TestClient(app), mp


def test_an_operator_sees_every_project(vault):
    # viewer None → no scoping (static key / auth disabled).
    app = FastAPI()
    app.include_router(vault_module.router, prefix="/api/v1")
    c = TestClient(app)
    names = {p["name"] for p in c.get("/api/v1/vault/projects").json()["data"]}
    assert names == {"alice-brief", "bob-brief", "legacy"}


def test_a_user_sees_only_owned_projects(vault):
    c, mp = client_as("alice", {"alice-brief"})
    try:
        names = {p["name"] for p in c.get("/api/v1/vault/projects").json()["data"]}
        assert names == {"alice-brief"}
    finally:
        mp.undo()


def test_reaching_another_users_project_is_404_not_403(vault):
    c, mp = client_as("alice", {"alice-brief"})
    try:
        assert c.get("/api/v1/vault/projects/bob-brief").status_code == 404
        assert c.get("/api/v1/vault/projects/bob-brief/out.md").status_code == 404
        assert c.get("/api/v1/vault/projects/bob-brief/out.md/download").status_code == 404
        assert c.delete("/api/v1/vault/projects/bob-brief/out.md").status_code == 404
        # legacy (unowned) is equally invisible to an identified user
        assert c.get("/api/v1/vault/projects/legacy").status_code == 404
    finally:
        mp.undo()


def test_a_user_can_reach_their_own_project(vault):
    c, mp = client_as("alice", {"alice-brief"})
    try:
        assert c.get("/api/v1/vault/projects/alice-brief").status_code == 200
        assert c.get("/api/v1/vault/projects/alice-brief/out.md").json()["data"]["content"] == "# alice-brief"
    finally:
        mp.undo()
