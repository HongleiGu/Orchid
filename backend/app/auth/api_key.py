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

    WebSockets cannot set headers from a browser, so the stream endpoint also
    accepts ?token=; see check_ws_token.
    """
    header = request.headers.get("x-api-key")
    if header:
        return header.strip()
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return None


def key_is_valid(candidate: str | None) -> bool:
    """Constant-time comparison against every configured key.

    Compared with hmac.compare_digest rather than `in`, so response timing does
    not leak how much of a guessed key was correct.
    """
    if not candidate:
        return False
    return any(
        hmac.compare_digest(candidate, known) for known in get_settings().api_keys
    )


def check_ws_token(token: str | None) -> bool:
    settings = get_settings()
    if not settings.auth_enabled:
        return True
    return key_is_valid(token)


def verify_startup_configuration() -> None:
    """Refuse to start unauthenticated in production; warn loudly in development.

    Failing open silently is how an API ends up on the public internet with no
    authentication at all, which is exactly what happened to this deployment.
    """
    settings = get_settings()
    if settings.auth_enabled:
        logger.info(
            "API authentication enabled (%d key(s), profile=%s)",
            len(settings.api_keys),
            settings.product_profile,
        )
        return

    if settings.app_env == "production":
        raise RuntimeError(
            "AUTH_API_KEYS is empty while APP_ENV=production. The API would accept "
            "anonymous requests, including run creation and marketplace installs. "
            "Set AUTH_API_KEYS, or set APP_ENV=development if this really is a "
            "local machine."
        )

    logger.warning(
        "API authentication is DISABLED (AUTH_API_KEYS is empty). Every endpoint is "
        "open to anyone who can reach this port. Acceptable on localhost; never "
        "expose this to a network."
    )
