"""Access control: API-key auth (OR-29) and the skill capability ceiling (OR-31)."""
from __future__ import annotations

import pytest

from app.config import DEFAULT_DENIED_SKILLS, Settings, get_settings
from app.skills.registry import Skill, SkillNotPermitted, SkillRegistry


@pytest.fixture(autouse=True)
def _clear_settings_cache():
    """get_settings is lru_cached; each test needs its own Settings instance."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _settings(**overrides) -> Settings:
    base = dict(auth_api_keys="", skills_allow="", skills_deny="",
                product_profile="full", app_env="development")
    base.update(overrides)
    return Settings(**base)


def _registry(*names: str) -> SkillRegistry:
    reg = SkillRegistry()
    for n in names:
        reg.register(Skill(name=n, description="", parameters={}, _execute=None))
    return reg


# ── config parsing ────────────────────────────────────────────────────────────

def test_empty_allowlist_means_no_allowlist_not_deny_everything():
    """A missing env var must not silently disable every skill."""
    s = _settings()
    assert s.skills_allowlist == set()
    assert s.skills_denylist == set()
    assert not s.auth_enabled


def test_lists_parse_and_strip_whitespace():
    s = _settings(auth_api_keys=" k1 , k2 ,", skills_deny="@orchid/a, @orchid/b")
    assert s.api_keys == {"k1", "k2"}
    assert s.skills_denylist == {"@orchid/a", "@orchid/b"}
    assert s.auth_enabled


def test_app_profile_denies_dangerous_skills_by_default():
    s = _settings(product_profile="app")
    assert DEFAULT_DENIED_SKILLS <= s.skills_denylist
    assert "@orchid/workspace_exec" in s.skills_denylist


def test_full_profile_does_not_apply_default_denies():
    """Existing deployments must be unaffected until they opt in."""
    assert _settings(product_profile="full").skills_denylist == set()


def test_explicit_allow_overrides_a_default_deny():
    s = _settings(product_profile="app", skills_allow="@orchid/workspace_exec")
    assert "@orchid/workspace_exec" not in s.skills_denylist


# ── registry enforcement ──────────────────────────────────────────────────────

def test_resolve_blocks_denied_skill(monkeypatch):
    monkeypatch.setattr("app.config.Settings", Settings)
    get_settings.cache_clear()
    monkeypatch.setenv("SKILLS_DENY", "@orchid/workspace_exec")

    reg = _registry("@orchid/web_search", "@orchid/workspace_exec")
    assert [s.name for s in reg.resolve(["@orchid/web_search"])] == ["@orchid/web_search"]

    with pytest.raises(SkillNotPermitted):
        reg.resolve(["@orchid/web_search", "@orchid/workspace_exec"])


def test_denied_skills_are_not_advertised(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("SKILLS_DENY", "@orchid/workspace_exec")

    reg = _registry("@orchid/web_search", "@orchid/workspace_exec")
    assert reg.names() == ["@orchid/web_search"]
    assert len(reg.all()) == 1
    # ...but diagnostics can still see everything registered.
    assert len(reg.all_unfiltered()) == 2


def test_allowlist_restricts_to_named_skills(monkeypatch):
    get_settings.cache_clear()
    monkeypatch.setenv("SKILLS_ALLOW", "@orchid/web_search")

    reg = _registry("@orchid/web_search", "@orchid/news_feeds")
    assert reg.names() == ["@orchid/web_search"]
    with pytest.raises(SkillNotPermitted):
        reg.resolve(["@orchid/news_feeds"])


def test_unknown_skill_still_raises_keyerror(monkeypatch):
    """Unknown and forbidden are different failures and must stay distinguishable."""
    get_settings.cache_clear()
    reg = _registry("@orchid/web_search")
    with pytest.raises(KeyError):
        reg.resolve(["@orchid/does_not_exist"])


# ── auth ──────────────────────────────────────────────────────────────────────

def test_key_validation(monkeypatch):
    from app.auth import api_key

    get_settings.cache_clear()
    monkeypatch.setenv("AUTH_API_KEYS", "correct-key,second-key")

    assert api_key.key_is_valid("correct-key")
    assert api_key.key_is_valid("second-key")
    assert not api_key.key_is_valid("wrong-key")
    assert not api_key.key_is_valid("")
    assert not api_key.key_is_valid(None)
    # A prefix of a valid key must not pass.
    assert not api_key.key_is_valid("correct")


def test_ws_token_open_when_auth_disabled(monkeypatch):
    from app.auth import api_key

    get_settings.cache_clear()
    monkeypatch.setenv("AUTH_API_KEYS", "")
    assert api_key.check_ws_token(None)

    get_settings.cache_clear()
    monkeypatch.setenv("AUTH_API_KEYS", "k")
    assert not api_key.check_ws_token(None)
    assert api_key.check_ws_token("k")


def test_production_without_keys_refuses_to_start(monkeypatch):
    from app.auth import api_key

    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_API_KEYS", "")

    with pytest.raises(RuntimeError, match="AUTH_API_KEYS"):
        api_key.verify_startup_configuration()


def test_production_with_keys_starts(monkeypatch):
    from app.auth import api_key

    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("AUTH_API_KEYS", "a-key")
    api_key.verify_startup_configuration()  # must not raise


def test_health_is_the_only_public_path():
    from app.auth import api_key

    assert api_key.is_public_path("/health")
    assert not api_key.is_public_path("/api/v1/agents")
    assert not api_key.is_public_path("/docs")
