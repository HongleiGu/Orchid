"""
Public contract types for the Orchid skill-runner.

Stable across implementations — `orchid-platform`'s microVM-per-run runner
implements the same `/execute`, `/list`, `/version` HTTP surface using these
exact types. Per future.md Tier 1.1.

Versioning rules
----------------
- `API_VERSION` (in main.py) bumps on breaking wire-format changes.
- Adding optional fields or new error codes is non-breaking.
- Renaming or removing fields, or repurposing an `ErrorCode`, is breaking.
"""
from __future__ import annotations

from enum import Enum

from fastapi import Header
from pydantic import BaseModel


class ErrorCode(str, Enum):
    """Machine-readable error codes — part of the public contract.

    Adding a new code is non-breaking; never repurpose an existing one.
    """
    SKILL_NOT_FOUND = "SKILL_NOT_FOUND"
    SKILL_NOT_LOADED = "SKILL_NOT_LOADED"
    PACKAGE_NOT_FOUND = "PACKAGE_NOT_FOUND"
    REQUIREMENTS_NOT_FOUND = "REQUIREMENTS_NOT_FOUND"
    EXEC_ERROR = "EXEC_ERROR"
    EXEC_TIMEOUT = "EXEC_TIMEOUT"
    DEP_INSTALL_FAILED = "DEP_INSTALL_FAILED"
    DEP_INSTALL_TIMEOUT = "DEP_INSTALL_TIMEOUT"
    VALIDATION_ERROR = "VALIDATION_ERROR"


class ErrorEnvelope(BaseModel):
    """Uniform error shape returned by the skill-runner.

    Used both as the body of HTTP 4xx responses (under `detail`) and as the
    `error` field of `ExecuteResponse` for failures that return HTTP 200
    (timeout, in-skill exception).
    """
    code: ErrorCode | str
    message: str
    details: dict | None = None


class RequestContext(BaseModel):
    """Per-request identity propagated from the orchestrator.

    The skill-runner does NOT validate auth — that lives at the orchestrator's
    public edge (Tier 1.3). The runner trusts these headers because it sits on
    a private network. In `orchid-platform` mode the same headers route the
    call to the correct microVM.
    """
    tenant_id: str
    user_id: str | None = None
    run_id: str | None = None
    request_id: str | None = None


def request_context(
    x_tenant_id: str = Header(default="default"),
    x_user_id: str | None = Header(default=None),
    x_run_id: str | None = Header(default=None),
    x_request_id: str | None = Header(default=None),
) -> RequestContext:
    return RequestContext(
        tenant_id=x_tenant_id,
        user_id=x_user_id,
        run_id=x_run_id,
        request_id=x_request_id,
    )
