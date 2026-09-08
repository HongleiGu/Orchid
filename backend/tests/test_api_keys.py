"""API key generation and hashing (OR-37).

The database-backed paths — issue, verify, revoke, disable — were exercised
against a real Postgres; this covers the pure logic, which is where a subtle
mistake would be silent.
"""
from __future__ import annotations

import hashlib

from app.auth.keys import KEY_PREFIX, generate_key, hash_key


def test_keys_are_prefixed_and_long():
    key = generate_key()
    assert key.startswith(KEY_PREFIX)
    # 32 random bytes, urlsafe-base64 encoded, plus the prefix.
    assert len(key) > 40


def test_keys_are_unique():
    assert len({generate_key() for _ in range(200)}) == 200


def test_hash_is_sha256_of_the_key():
    """Deliberately a fast hash, not bcrypt/argon2.

    A key is 256 bits of CSPRNG output, so there is no dictionary to attack; a
    slow salted KDF would buy nothing and would force scanning every row per
    request, since a salted hash cannot be looked up by index.
    """
    key = "orc_example"
    assert hash_key(key) == hashlib.sha256(key.encode()).hexdigest()
    assert len(hash_key(key)) == 64


def test_hash_is_stable_and_distinct():
    a, b = generate_key(), generate_key()
    assert hash_key(a) == hash_key(a)
    assert hash_key(a) != hash_key(b)


def test_hash_does_not_contain_the_key():
    """Obvious, but it is the property the whole design rests on."""
    key = generate_key()
    assert key not in hash_key(key)
    assert key[len(KEY_PREFIX):] not in hash_key(key)


# ── Whether authentication is enforced at all ─────────────────────────────────
#
# The defect these cover: `Settings.auth_enabled` reports only static keys, and
# the middleware short-circuited on it. A deployment that had migrated entirely
# to issued keys therefore passed startup verification, logged that
# authentication was enabled, and served every endpoint anonymously.

import pytest

from app.auth import api_key as api_key_mod
from app.auth.api_key import auth_is_enforced, reset_auth_state
from app.config import get_settings


@pytest.fixture(autouse=True)
def _reset_auth_state():
    reset_auth_state()
    get_settings.cache_clear()
    yield
    reset_auth_state()
    get_settings.cache_clear()


async def test_static_keys_enforce_without_touching_the_database(monkeypatch):
    monkeypatch.setenv("AUTH_API_KEYS", "static-key")
    get_settings.cache_clear()

    async def _explode():
        raise AssertionError("must not probe the database when static keys exist")

    monkeypatch.setattr(api_key_mod, "_has_active_db_key", _explode)
    assert await auth_is_enforced() is True


async def test_issued_keys_alone_still_enforce(monkeypatch):
    """The regression. No AUTH_API_KEYS, one database key: authentication is on."""
    monkeypatch.setenv("AUTH_API_KEYS", "")
    get_settings.cache_clear()

    async def _yes():
        return True

    monkeypatch.setattr(api_key_mod, "_has_active_db_key", _yes)
    assert await auth_is_enforced() is True


async def test_no_credentials_anywhere_leaves_it_open(monkeypatch):
    """Localhost development. Startup warns loudly; production refuses to boot."""
    monkeypatch.setenv("AUTH_API_KEYS", "")
    get_settings.cache_clear()

    async def _no():
        return False

    monkeypatch.setattr(api_key_mod, "_has_active_db_key", _no)
    assert await auth_is_enforced() is False


async def test_enforcement_latches_on_and_never_off(monkeypatch):
    """Revoking the last key must refuse requests, not admit them."""
    monkeypatch.setenv("AUTH_API_KEYS", "")
    get_settings.cache_clear()

    async def _yes():
        return True

    monkeypatch.setattr(api_key_mod, "_has_active_db_key", _yes)
    assert await auth_is_enforced() is True

    async def _explode():
        raise AssertionError("must not re-probe once enforcement has latched on")

    monkeypatch.setattr(api_key_mod, "_has_active_db_key", _explode)
    assert await auth_is_enforced() is True


async def test_the_database_probe_is_throttled(monkeypatch):
    """This runs in the request path, so an unconfigured deployment must not
    issue a query per request."""
    monkeypatch.setenv("AUTH_API_KEYS", "")
    get_settings.cache_clear()

    calls = 0

    async def _count():
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(api_key_mod, "_has_active_db_key", _count)
    for _ in range(20):
        assert await auth_is_enforced() is False
    assert calls == 1, f"probed {calls} times"
