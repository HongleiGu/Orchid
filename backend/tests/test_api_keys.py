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
