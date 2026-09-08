"""Three-layer permission model: ceiling, plan, membership (OR-38).

The property under test throughout is that each layer may only narrow the one
above it. A plan is config, so it is trusted to describe a tier — but it is not
trusted to hand out capability the deployment ceiling withheld, because a plan
naming a denied skill is exactly what a mistake in a hand-edited catalog looks
like.

Membership lives in the database and so is exercised against a real Postgres;
what is covered here is the resolution logic, where a wrong answer is silent.
"""
from __future__ import annotations

import json

import pytest

from app.config import get_settings
from app.plans.registry import (
    Plan,
    load_plans,
    plan_registry,
    resolve_permissions,
)


@pytest.fixture(autouse=True)
def _isolate_registry_and_settings():
    get_settings.cache_clear()
    plan_registry.clear()
    yield
    plan_registry.clear()
    get_settings.cache_clear()


def _register(**kwargs) -> Plan:
    plan = Plan(**kwargs)
    plan_registry.register(plan)
    return plan


# ── The narrowing rule ────────────────────────────────────────────────────────

def test_a_plan_cannot_widen_the_ceiling(monkeypatch):
    """The central guarantee. A plan listing a skill the deployment never
    allowed does not thereby grant it."""
    monkeypatch.setenv("SKILLS_ALLOW", "@orchid/web_search,@orchid/file_read")
    monkeypatch.setenv("MODELS_ALLOW", "deepseek/deepseek-chat")
    get_settings.cache_clear()

    _register(
        id="greedy",
        skills=["@orchid/web_search", "@orchid/workspace_exec"],
        models=["deepseek/deepseek-chat", "openai/gpt-4o"],
    )

    perms = resolve_permissions("greedy")
    assert perms.skills == frozenset({"@orchid/web_search"})
    assert perms.models == frozenset({"deepseek/deepseek-chat"})


def test_a_wildcard_plan_gets_the_ceiling_not_everything(monkeypatch):
    """A wildcard means "all the deployment allows", never "all that exists"."""
    monkeypatch.setenv("SKILLS_ALLOW", "@orchid/web_search")
    monkeypatch.setenv("MODELS_ALLOW", "")
    get_settings.cache_clear()

    _register(id="unlimited", skills=["*"], models=["*"])

    perms = resolve_permissions("unlimited")
    assert perms.skills == frozenset({"@orchid/web_search"})
    # No model ceiling configured, so the plan's wildcard stays unrestricted.
    assert perms.models is None


def test_a_plan_narrows_when_there_is_no_ceiling(monkeypatch):
    """With no deployment allowlist the plan's own list is the restriction."""
    monkeypatch.setenv("SKILLS_ALLOW", "")
    get_settings.cache_clear()

    _register(id="narrow", skills=["@orchid/web_search"])

    assert resolve_permissions("narrow").skills == frozenset({"@orchid/web_search"})


def test_a_plan_naming_only_denied_skills_grants_none(monkeypatch):
    """Not an error, and not a fallback to the ceiling: an empty grant."""
    monkeypatch.setenv("SKILLS_ALLOW", "@orchid/web_search")
    get_settings.cache_clear()

    _register(id="wrong", skills=["@orchid/workspace_exec"])

    assert resolve_permissions("wrong").skills == frozenset()


# ── No plan ───────────────────────────────────────────────────────────────────

def test_no_plan_falls_back_to_the_ceiling(monkeypatch):
    """Introducing plans must not break a deployment that has none."""
    monkeypatch.setenv("SKILLS_ALLOW", "@orchid/web_search")
    monkeypatch.setenv("MODELS_ALLOW", "")
    get_settings.cache_clear()

    perms = resolve_permissions(None)
    assert perms.plan_id is None
    assert perms.skills == frozenset({"@orchid/web_search"})
    assert perms.models is None
    assert perms.templates is None


def test_an_unknown_plan_id_behaves_as_no_plan():
    """A stale plan_id in the database — a tier that was retired — must not
    crash a run, and must not grant anything the ceiling does not."""
    perms = resolve_permissions("was-removed-in-v2")
    assert perms.plan_id is None
    assert perms.templates is None


# ── Templates ─────────────────────────────────────────────────────────────────

def test_a_plan_restricts_which_templates_may_run():
    _register(id="trial", templates=["china-market-daily-brief"])

    perms = resolve_permissions("trial")
    assert perms.allows_template("china-market-daily-brief")
    assert not perms.allows_template("some-other-template")


def test_wildcard_templates_allow_anything_in_the_catalog():
    _register(id="standard", templates=["*"])

    perms = resolve_permissions("standard")
    assert perms.templates is None
    assert perms.allows_template("anything-at-all")


# ── Quotas ────────────────────────────────────────────────────────────────────

def test_plan_quotas_are_carried_through():
    _register(id="trial", max_cost_per_day=1.0, max_cost_per_month=5.0, max_runs_per_day=3)

    perms = resolve_permissions("trial")
    assert perms.max_cost_per_day == 1.0
    assert perms.max_cost_per_month == 5.0
    assert perms.max_runs_per_day == 3


def test_a_plan_with_no_quota_imposes_none():
    _register(id="open")
    perms = resolve_permissions("open")
    assert perms.max_cost_per_day is None
    assert perms.max_cost_per_month is None


# ── Catalog loading ───────────────────────────────────────────────────────────

def test_shipped_catalog_loads():
    assert load_plans() >= 1
    assert plan_registry.ids()


def test_a_missing_catalog_is_not_an_error(tmp_path):
    """A single-customer deployment defines no tiers; everyone runs at the
    ceiling. That must not be a startup failure."""
    assert load_plans(tmp_path / "absent.json") == 0


def test_an_unreadable_catalog_does_not_crash_startup(tmp_path):
    bad = tmp_path / "plans.json"
    bad.write_text("{not json", encoding="utf-8")
    assert load_plans(bad) == 0


def test_a_malformed_plan_is_skipped_and_the_rest_load(tmp_path):
    path = tmp_path / "plans.json"
    path.write_text(json.dumps([
        {"name": "no id here"},
        {"id": "good", "name": "Good"},
    ]), encoding="utf-8")

    assert load_plans(path) == 1
    assert plan_registry.ids() == ["good"]


# ── PLAN_REQUIRED ─────────────────────────────────────────────────────────────

class _NoSubscriptionSession:
    """Stands in for a session where the user holds no subscription."""

    async def execute(self, *_args, **_kwargs):
        class _Result:
            def scalar_one_or_none(self):
                return None
        return _Result()


async def test_plan_required_denies_an_unsubscribed_user(monkeypatch):
    from app.plans.service import permissions_for

    monkeypatch.setenv("PLAN_REQUIRED", "true")
    get_settings.cache_clear()

    perms = await permissions_for(_NoSubscriptionSession(), "user-1")
    assert perms.plan_id is None
    # Empty sets, not None: None means unrestricted and would grant everything.
    assert perms.templates == frozenset()
    assert perms.skills == frozenset()
    assert perms.models == frozenset()
    assert perms.max_cost_per_day == 0.0
    assert not perms.allows_template("china-market-daily-brief")


async def test_plan_not_required_lets_an_unsubscribed_user_run(monkeypatch):
    from app.plans.service import permissions_for

    monkeypatch.setenv("PLAN_REQUIRED", "false")
    get_settings.cache_clear()

    perms = await permissions_for(_NoSubscriptionSession(), "user-1")
    assert perms.allows_template("china-market-daily-brief")


async def test_an_anonymous_caller_is_unaffected_by_plans(monkeypatch):
    """A static deployment key carries no identity, so there is no subscription
    to look up. It authenticates as the operator and runs at the ceiling."""
    from app.plans.service import permissions_for

    monkeypatch.setenv("PLAN_REQUIRED", "false")
    get_settings.cache_clear()

    perms = await permissions_for(_NoSubscriptionSession(), None)
    assert perms.allows_template("china-market-daily-brief")
