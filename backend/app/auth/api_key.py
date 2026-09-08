"""API-key authentication for the public API.

Static keys from config for now. OR-37 replaces this with hashed, individually
revocable keys in the database — revocation has to take effect without a
restart, which is the one thing config cannot do.

Deliberately a middleware rather than a per-route dependency: routers all mount
under a single prefix in main.py, so this is one place to audit and there is no
way to forget a route when adding one.
"""
from __future__ import annotations

import hmac
import logging

from starlette.requests import Request

from app.config import get_settings

logger = logging.getLogger(__name__)

# Paths reachable without a key.
#   /health   — container healthchecks run before any key is provisioned
# Everything else, including the OpenAPI docs, requires one.
PUBLIC_PATHS: frozenset[str] = frozenset({"/health"})


def is_public_path(path: str) -> bool:
    return path in PUBLIC_PATHS


def extract_key(request: Request) -> str | None:
    """Read the key from either header form.

    Headers only, deliberately: the run stream is SSE rather than a WebSocket,
    so every route authenticates the same way and no credential travels in a
    query string where access logs would capture it.
    """
    header = request.headers.get("x-api-key")
    if header:
        return header.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def key_is_valid(candidate: str | None) -> bool:
    """Check a key against the static AUTH_API_KEYS list.

    Compared with hmac.compare_digest rather than `in`, so response timing does
    not leak how much of a guessed key was correct.

    Static keys remain supported alongside database-backed ones (OR-37): they
    are how the current deployment authenticates, and an upgrade that
    invalidated them would lock an operator out of their own server. They carry
    no identity, so a request authenticated this way has no user attached.
    """
    if not candidate:
        return False
    return any(
        hmac.compare_digest(candidate, known) for known in get_settings().api_keys
    )


async def resolve_user(candidate: str | None):
    """Resolve a key to a User, or None for static/invalid keys.

    Separate from key_is_valid because the middleware must stay synchronous and
    cheap for the static path; only requests that need identity pay for a
    database lookup.
    """
    if not candidate:
        return None

    from app.auth.keys import verify_key
    from app.db.session import AsyncSessionLocal

    try:
        async with AsyncSessionLocal() as db:
            user = await verify_key(db, candidate)
            if user is not None:
                await db.commit()      # persist the coarse last_used_at touch
            return user
    except Exception as exc:
        # Fail closed. This runs inside the auth middleware, so letting a
        # database error propagate would turn every request into a 500 while
        # the database is unreachable — including requests bearing a valid
        # static key, which needs no database at all. Rejecting is the safe
        # answer: a caller is denied rather than admitted or crashed.
        logger.warning("API key lookup failed, rejecting the request: %s", exc)
        return None


async def authenticate(candidate: str | None) -> tuple[bool, str | None]:
    """Authenticate a key, returning (ok, user_id).

    user_id is None for a static AUTH_API_KEYS key: those authenticate but carry
    no identity, so their runs are unattributed. That is a deliberate,
    distinguishable state rather than a failure — it is how the operator's own
    deployment key behaves.
    """
    if key_is_valid(candidate):
        return True, None
    user = await resolve_user(candidate)
    return (user is not None), (user.id if user else None)


# Whether authentication is being enforced. Not simply `settings.auth_enabled`:
# that reports only static keys, so a deployment which has migrated entirely to
# issued keys (OR-37) would report "no keys configured" and skip the middleware
# altogether — serving the whole API anonymously while startup logged that
# authentication was enabled. Latched on, never off: if every key is later
# revoked, requests are refused rather than admitted.
_db_keys_seen = False
_last_db_probe = 0.0
# How long a deployment with no credentials at all may go before noticing that
# its first key has been issued. Only paid while there are none, so this is not
# a per-request cost in any configured deployment.
_DB_PROBE_INTERVAL_SECONDS = 30.0


async def auth_is_enforced() -> bool:
    """Whether any credential source exists, so requests must be authenticated.

    Static keys answer this for free. Otherwise the database is probed, at most
    every 30 seconds, until a key is found — after which the answer is latched.
    That also means issuing the very first key switches authentication on
    without a restart, which is the behaviour OR-37 wanted for revocation.
    """
    global _db_keys_seen, _last_db_probe

    if get_settings().api_keys or _db_keys_seen:
        return True

    from time import monotonic

    now = monotonic()
    if _last_db_probe and now - _last_db_probe < _DB_PROBE_INTERVAL_SECONDS:
        return False

    _last_db_probe = now
    if await _has_active_db_key():
        _db_keys_seen = True
        logger.info("Database API key found — authentication is now enforced")
    return _db_keys_seen


def reset_auth_state() -> None:
    """Forget the latched state. For tests; nothing in the app calls it."""
    global _db_keys_seen, _last_db_probe
    _db_keys_seen = False
    _last_db_probe = 0.0


async def _has_active_db_key() -> bool:
    """Whether any usable database key exists. Never raises."""
    try:
        from sqlalchemy import select

        from app.db.models.user import ApiKey, User
        from app.db.session import AsyncSessionLocal

        async with AsyncSessionLocal() as db:
            row = await db.execute(
                select(ApiKey.id)
                .join(User, ApiKey.user_id == User.id)
                .where(ApiKey.revoked_at.is_(None), User.status == "active")
                .limit(1)
            )
            return row.scalar_one_or_none() is not None
    except Exception as exc:      # migrations not yet applied, DB unreachable, ...
        logger.debug("Could not check for database API keys: %s", exc)
        return False


async def verify_startup_configuration() -> None:
    """Refuse to start unauthenticated in production; warn loudly in development.

    Failing open silently is how an API ends up on the public internet with no
    authentication at all, which is exactly what happened to this deployment.

    Either source counts: a static AUTH_API_KEYS list, or at least one live
    database key (OR-37). A deployment that has migrated entirely to issued keys
    must not be told to set a static one.
    """
    settings = get_settings()
    if settings.auth_enabled:
        logger.info(
            "API authentication enabled (%d static key(s), profile=%s)",
            len(settings.api_keys),
            settings.product_profile,
        )
        return

    if await auth_is_enforced():
        logger.info(
            "API authentication enabled (database keys, profile=%s)",
            settings.product_profile,
        )
        return

    if settings.app_env == "production":
        raise RuntimeError(
            "No API keys configured while APP_ENV=production: AUTH_API_KEYS is "
            "empty and no active database key exists. The API would accept "
            "anonymous requests, including run creation. Either set "
            "AUTH_API_KEYS, or issue a key with: "
            "python -m app.auth.keys create <identifier>"
        )

    logger.warning(
        "API authentication is DISABLED (no static keys and no database keys). "
        "Every endpoint is open to anyone who can reach this port. Acceptable on "
        "localhost; never expose this to a network."
    )
