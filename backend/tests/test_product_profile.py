"""Run-only profile: API surface allowlist (OR-30) and model ceiling (OR-32)."""
from __future__ import annotations

import pytest

from app.auth.profile import is_request_permitted
from app.config import get_settings
from app.models.client import ModelNotPermitted, ensure_model_permitted


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


# ── API surface allowlist ─────────────────────────────────────────────────────

@pytest.mark.parametrize("method,path", [
    ("GET", "/api/v1/templates"),
    ("GET", "/api/v1/templates/china-market-daily-brief"),
    ("POST", "/api/v1/templates/china-market-daily-brief/run"),
    ("GET", "/api/v1/runs"),
    ("GET", "/api/v1/runs/01ABC"),
    ("GET", "/api/v1/runs/01ABC/stream"),
    ("POST", "/api/v1/runs/01ABC/cancel"),
    ("GET", "/api/v1/budget/usage"),
    ("GET", "/api/v1/budget/usage/run/01ABC"),
    ("GET", "/api/v1/vault/notes/x.md"),
])
def test_allowed(method, path):
    assert is_request_permitted(method, path)


@pytest.mark.parametrize("method,path", [
    # Authoring — the whole point of the profile.
    ("POST", "/api/v1/agents"),
    ("PUT", "/api/v1/agents/01ABC"),
    ("DELETE", "/api/v1/agents/01ABC"),
    ("POST", "/api/v1/workflow-maker/draft"),
    ("POST", "/api/v1/skill-writer/save"),
    # Remote code execution by design.
    ("POST", "/api/v1/marketplace/install"),
    # Importing a pipeline creates agents; that is authoring by another name.
    ("POST", "/api/v1/config/import"),
    # Deployment policy, not a user setting.
    ("POST", "/api/v1/budget/limits"),
    # Reading agents still exposes prompts, which are the product.
    ("GET", "/api/v1/agents"),
    # Writes to otherwise-allowed prefixes.
    ("DELETE", "/api/v1/vault/notes/x.md"),
    ("POST", "/api/v1/tasks"),
    # Running an arbitrary task is exactly what OR-33 forbids: only a template
    # in the shipped catalog may run.
    ("POST", "/api/v1/tasks/01ABC/trigger"),
    ("POST", "/api/v1/tasks/01ABC/trigger/batch"),
    # /tasks is no longer readable — the catalog serves that need, and task
    # names and descriptions are workflow internals.
    ("GET", "/api/v1/tasks"),
    ("GET", "/api/v1/tasks/01ABC"),
    # Creating a run directly would sidestep the template gate.
    ("POST", "/api/v1/runs"),
    # Templates ship with the release; there is no write surface.
    ("POST", "/api/v1/templates"),
    ("DELETE", "/api/v1/templates/china-market-daily-brief"),
])
def test_denied(method, path):
    assert not is_request_permitted(method, path)


def test_unknown_future_route_is_denied_by_default():
    """The reason this is an allowlist: a route added later must be closed
    until someone opens it deliberately."""
    assert not is_request_permitted("POST", "/api/v1/templates/import")
    assert not is_request_permitted("GET", "/api/v1/whatever-comes-next")


def test_prefix_matching_is_not_sloppy():
    """`/api/v1/runsomething` must not pass because it starts with `/api/v1/run`."""
    assert not is_request_permitted("GET", "/api/v1/runsomething")
    assert not is_request_permitted("GET", "/api/v1/vaultsomething")


# ── Model ceiling ─────────────────────────────────────────────────────────────

def test_empty_allowlist_permits_any_model(monkeypatch):
    monkeypatch.setenv("MODELS_ALLOW", "")
    get_settings.cache_clear()
    ensure_model_permitted("deepseek/deepseek-chat")   # must not raise


def test_allowlist_permits_named_models(monkeypatch):
    monkeypatch.setenv("MODELS_ALLOW", "deepseek/deepseek-chat, deepseek/deepseek-reasoner")
    get_settings.cache_clear()
    ensure_model_permitted("deepseek/deepseek-chat")
    ensure_model_permitted("deepseek/deepseek-reasoner")


def test_allowlist_blocks_everything_else(monkeypatch):
    monkeypatch.setenv("MODELS_ALLOW", "deepseek/deepseek-chat")
    get_settings.cache_clear()
    with pytest.raises(ModelNotPermitted, match="not permitted"):
        ensure_model_permitted("openrouter/anthropic/claude-sonnet-4.6")


def test_error_names_the_allowed_models(monkeypatch):
    """The message has to be actionable — a bare 'denied' sends someone reading
    source to find out which models exist."""
    monkeypatch.setenv("MODELS_ALLOW", "deepseek/deepseek-chat")
    get_settings.cache_clear()
    with pytest.raises(ModelNotPermitted) as exc:
        ensure_model_permitted("gpt-4o")
    assert "deepseek/deepseek-chat" in str(exc.value)
