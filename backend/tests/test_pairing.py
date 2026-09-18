"""Device pairing (OR-47) — the logic that decides what a code is.

The database paths (atomic single use, expiry, one outstanding code per user,
the issued key authenticating) are exercised against a real Postgres through the
running API; see the verification notes on OR-47.
"""
from __future__ import annotations

import math

import pytest

from app.auth import pairing
from app.auth.api_key import PUBLIC_PATHS, is_public_path
from app.auth.profile import is_request_permitted


# ── codes ────────────────────────────────────────────────────────────────────

def test_codes_use_crockford_base32_and_the_documented_length():
    for _ in range(200):
        code = pairing.generate_code()
        assert len(code) == pairing.CODE_LENGTH
        assert set(code) <= set(pairing.CODE_ALPHABET)
        assert not set(code) & set("ILOU"), "look-alike characters must never be issued"


def test_the_code_space_is_at_least_fifty_bits():
    """The TTL and the absence of a rate limiter are justified by this number."""
    assert math.log2(len(pairing.CODE_ALPHABET) ** pairing.CODE_LENGTH) >= 50


def test_codes_do_not_repeat():
    assert len({pairing.generate_code() for _ in range(2000)}) == 2000


def test_formatted_codes_are_grouped_for_reading():
    assert pairing.format_code("ABCDE12345") == "ABCDE-12345"


@pytest.mark.parametrize("typed, expected", [
    ("ABCDE-FGHJK", "ABCDEFGHJK"),
    ("abcde fghjk", "ABCDEFGHJK"),
    ("  abcde-fghjk\n", "ABCDEFGHJK"),
    # Crockford: the removed look-alikes decode to what they resemble.
    ("OOOOO-IIIII", "0000011111"),
    ("ooooo-lllll", "0000011111"),
])
def test_normalization_accepts_what_people_type(typed, expected):
    assert pairing.normalize_code(typed) == expected


@pytest.mark.parametrize("bad", ["", "ABCD", "ABCDE-FGHJKX", "ABCDE-FGHU!", None, 12345])
def test_malformed_codes_are_rejected_before_any_lookup(bad):
    assert pairing.normalize_code(bad) is None


def test_the_same_code_typed_differently_hashes_the_same():
    a = pairing.hash_code(pairing.normalize_code("abcde-fghjk"))
    b = pairing.hash_code(pairing.normalize_code("ABCDE FGHJK"))
    assert a == b and len(a) == 64


def test_the_hash_does_not_contain_the_code():
    code = pairing.generate_code()
    assert code not in pairing.hash_code(code)


async def test_redeeming_a_malformed_code_fails_without_touching_the_database():
    class Explodes:
        async def execute(self, *_a, **_k):
            raise AssertionError("a malformed code must not reach the database")

    with pytest.raises(pairing.PairingError):
        await pairing.redeem(Explodes(), "not a code", "phone")


# ── device names (unauthenticated input) ─────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("iPhone 15", "iPhone 15"),
    ("  小米手机  ", "小米手机"),
    ("evil\x00\x07‮name", "evilname"),     # control and bidi-override characters
    ("", "device"),
    (None, "device"),
])
def test_device_names_are_cleaned(raw, expected):
    assert pairing.clean_device_name(raw) == expected


def test_device_names_are_capped():
    assert len(pairing.clean_device_name("x" * 500)) == pairing.DEVICE_NAME_MAX


# ── surface ──────────────────────────────────────────────────────────────────

def test_only_redemption_is_public():
    assert PUBLIC_PATHS == frozenset({"/health", "/api/v1/pairing/redeem"})
    assert is_public_path("/api/v1/pairing/redeem")
    assert not is_public_path("/api/v1/pairing")
    assert not is_public_path("/api/v1/pairing/01ABC")


def test_the_run_only_profile_allows_pairing_but_nothing_adjacent():
    assert is_request_permitted("POST", "/api/v1/pairing")
    assert is_request_permitted("GET", "/api/v1/pairing/01ABC")
    assert not is_request_permitted("DELETE", "/api/v1/pairing/01ABC")
    assert not is_request_permitted("GET", "/api/v1/pairing")
