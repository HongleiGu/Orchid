"""
Skill-runner: sandboxed micro-service for executing skills.

Public contract — versioned at /version. Stable across orchid-platform
implementations (per future.md Tier 1.1). Shared types live in `contracts.py`.

Endpoints
---------
GET  /version           → {"runner_version": str, "api_version": str}
GET  /health            → {"status": "ok", "loaded": int}
GET  /list              → list[SkillInfo]   (loaded skills + their schemas)
POST /execute           → run a skill by name with kwargs
POST /install-deps      → pip install from a requirements.txt path
POST /reload            → rescan packages dir, reload all
POST /reload/{name}     → reload a single package
POST /unload/{name}     → unload a single package

Request context (all endpoints)
-------------------------------
Optional headers identify the caller for logging, tracing, and (in
orchid-platform mode) per-tenant routing. The runner does NOT validate auth —
that's enforced at the orchestrator's public edge (Tier 1.3).
  X-Tenant-Id    defaults to "default"
  X-User-Id      optional
  X-Run-Id       optional
  X-Request-Id   optional

All responses include:
  X-Orchid-Runner-Version
  X-Orchid-Runner-Api-Version

Execute contract
----------------
Request:
  {"skill_name": str, "kwargs": dict}
Response (200):
  {"result": str, "error": ErrorEnvelope | null}
Response (4xx):
  {"detail": ErrorEnvelope}

ErrorEnvelope = {"code": str, "message": str, "details": dict | null}.
Codes are part of the contract — see `contracts.ErrorCode`.

A skill is bounded by its SKILL.md `timeout:` field (default 30s).
On timeout or in-skill exception, response is HTTP 200 with empty result and
an ErrorEnvelope (code = EXEC_TIMEOUT or EXEC_ERROR).
HTTP 404 is used for "skill / package not loaded".

Streaming semantics
-------------------
API v2 is request/response only. Long-running skills are synchronous HTTP calls
bounded by SKILL.md `timeout:` and MAX_EXECUTE_TIMEOUT. A future streaming API
must use a new endpoint or API version.
"""
from __future__ import annotations

import asyncio
import logging
import os
import subprocess
import sys
import traceback
from contextlib import asynccontextmanager

# Ensure /app (where skill_lib lives) is importable from dynamically loaded
# skill modules. spec_from_file_location does not inherit cwd by default.
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from contracts import ErrorCode, ErrorEnvelope, RequestContext, request_context
from loader import LoadedSkill, get_loaded, get_skill, load_single, scan_and_load, unload, PACKAGES_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Bumped only as a hard ceiling; per-skill timeout comes from SKILL.md.
DEFAULT_EXECUTE_TIMEOUT = 30
MAX_EXECUTE_TIMEOUT = 600

RUNNER_VERSION = "0.3.0"
# Bumped to 2: /execute response `error` is now ErrorEnvelope (was bare str),
# and 4xx detail bodies are now ErrorEnvelope (was bare str).
API_VERSION = "2"


@asynccontextmanager
async def lifespan(app: FastAPI):
    scan_and_load()
    yield


app = FastAPI(title="Orchid Skill Runner", version=RUNNER_VERSION, lifespan=lifespan)


@app.middleware("http")
async def add_contract_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Orchid-Runner-Version"] = RUNNER_VERSION
    response.headers["X-Orchid-Runner-Api-Version"] = API_VERSION
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "detail": ErrorEnvelope(
                code=ErrorCode.VALIDATION_ERROR,
                message="Request validation failed",
                details={"errors": exc.errors()},
            ).model_dump(),
        },
        headers={
            "X-Orchid-Runner-Version": RUNNER_VERSION,
            "X-Orchid-Runner-Api-Version": API_VERSION,
        },
    )


# ── Schemas ───────────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    skill_name: str
    kwargs: dict = {}


class ExecuteResponse(BaseModel):
    result: str
    error: ErrorEnvelope | None = None


class InstallDepsRequest(BaseModel):
    requirements_path: str  # path relative to /packages/node_modules/


class InstallDepsResponse(BaseModel):
    status: str
    output: str = ""
    error: ErrorEnvelope | None = None


class SkillInfo(BaseModel):
    name: str
    description: str
    parameters: dict
    pkg_type: str
    package_dir: str
    timeout: int = 30


class VersionInfo(BaseModel):
    runner_version: str
    api_version: str


# ── Helpers ───────────────────────────────────────────────────────────────────

def _http_error(status: int, code: ErrorCode, message: str, **details) -> HTTPException:
    """Raise HTTPException with an ErrorEnvelope as `detail`."""
    return HTTPException(
        status_code=status,
        detail=ErrorEnvelope(
            code=code,
            message=message,
            details=details or None,
        ).model_dump(),
    )


def _log_op(ctx: RequestContext, op: str, **fields) -> None:
    """Structured per-request audit line. Same fields will feed OTel later."""
    extras = " ".join(f"{k}={v!r}" for k, v in fields.items())
    logger.info(
        "op=%s tenant=%s user=%s run=%s request=%s %s",
        op, ctx.tenant_id, ctx.user_id, ctx.run_id, ctx.request_id, extras,
    )


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "loaded": len(get_loaded())}


@app.get("/version", response_model=VersionInfo)
async def version():
    return VersionInfo(runner_version=RUNNER_VERSION, api_version=API_VERSION)


@app.get("/list", response_model=list[SkillInfo])
async def list_skills():
    return [
        SkillInfo(
            name=s.name,
            description=s.description,
            parameters=s.parameters,
            pkg_type=s.pkg_type,
            package_dir=str(s.package_dir),
            timeout=s.timeout,
        )
        for s in get_loaded().values()
    ]


@app.post("/execute", response_model=ExecuteResponse)
async def execute(
    req: ExecuteRequest,
    ctx: RequestContext = Depends(request_context),
):
    _log_op(ctx, "execute", skill=req.skill_name)
    skill = get_skill(req.skill_name)
    if not skill:
        raise _http_error(
            404,
            ErrorCode.SKILL_NOT_FOUND,
            f"Skill {req.skill_name!r} not loaded",
            skill_name=req.skill_name,
        )

    timeout = min(skill.timeout or DEFAULT_EXECUTE_TIMEOUT, MAX_EXECUTE_TIMEOUT)
    try:
        result = await asyncio.wait_for(
            _run_skill(skill, req.kwargs),
            timeout=timeout,
        )
        return ExecuteResponse(result=result)
    except asyncio.TimeoutError:
        return ExecuteResponse(
            result="",
            error=ErrorEnvelope(
                code=ErrorCode.EXEC_TIMEOUT,
                message=f"Skill {req.skill_name!r} timed out after {timeout}s",
                details={"timeout_seconds": timeout},
            ),
        )
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error(
            "Skill %r execution error (tenant=%s, run=%s, request=%s):\n%s",
            req.skill_name, ctx.tenant_id, ctx.run_id, ctx.request_id, tb,
        )
        return ExecuteResponse(
            result="",
            error=ErrorEnvelope(
                code=ErrorCode.EXEC_ERROR,
                message=str(exc),
                details={"exception_type": type(exc).__name__},
            ),
        )


@app.post("/install-deps", response_model=InstallDepsResponse)
async def install_deps(
    req: InstallDepsRequest,
    ctx: RequestContext = Depends(request_context),
):
    """Install Python dependencies from a package's requirements.txt."""
    _log_op(ctx, "install-deps", requirements_path=req.requirements_path)
    req_path = PACKAGES_DIR / req.requirements_path
    if not req_path.exists():
        raise _http_error(
            404,
            ErrorCode.REQUIREMENTS_NOT_FOUND,
            f"requirements.txt not found at {req.requirements_path}",
            requirements_path=req.requirements_path,
        )

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", str(req_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return InstallDepsResponse(
                status="error",
                output=result.stderr,
                error=ErrorEnvelope(
                    code=ErrorCode.DEP_INSTALL_FAILED,
                    message="pip install failed",
                    details={"returncode": result.returncode},
                ),
            )
        return InstallDepsResponse(status="ok", output=result.stdout)
    except subprocess.TimeoutExpired:
        return InstallDepsResponse(
            status="error",
            output="pip install timed out",
            error=ErrorEnvelope(
                code=ErrorCode.DEP_INSTALL_TIMEOUT,
                message="pip install timed out",
                details={"timeout_seconds": 120},
            ),
        )


@app.post("/reload")
async def reload_all(ctx: RequestContext = Depends(request_context)):
    """Rescan packages directory and reload all skills."""
    _log_op(ctx, "reload-all")
    loaded = scan_and_load()
    return {"status": "ok", "loaded": len(loaded)}


@app.post("/reload/{name}")
async def reload_single(name: str, ctx: RequestContext = Depends(request_context)):
    """Reload a single package by scanning for it in packages dir."""
    _log_op(ctx, "reload", skill=name)
    for pkg_dir in _find_package_dir(name):
        skill = load_single(pkg_dir)
        if skill:
            return {"status": "ok", "name": skill.name, "type": skill.pkg_type}
    raise _http_error(
        404,
        ErrorCode.PACKAGE_NOT_FOUND,
        f"Package for skill {name!r} not found in packages dir",
        skill_name=name,
    )


@app.post("/unload/{name}")
async def unload_skill(name: str, ctx: RequestContext = Depends(request_context)):
    _log_op(ctx, "unload", skill=name)
    if unload(name):
        return {"status": "ok"}
    raise _http_error(
        404,
        ErrorCode.SKILL_NOT_LOADED,
        f"Skill {name!r} not loaded",
        skill_name=name,
    )


# ── Internal ──────────────────────────────────────────────────────────────────

async def _run_skill(skill: LoadedSkill, kwargs: dict) -> str:
    """Execute a skill, handling both sync and async execute functions."""
    result = skill.execute_fn(**kwargs)
    if asyncio.iscoroutine(result) or asyncio.isfuture(result):
        result = await result
    return str(result)


def _find_package_dir(name: str):
    """Search packages dir for a package whose loaded name matches."""
    if not PACKAGES_DIR.exists():
        return
    for entry in PACKAGES_DIR.iterdir():
        if entry.is_dir() and entry.name.startswith("@"):
            for sub in entry.iterdir():
                if sub.is_dir():
                    yield sub
        elif entry.is_dir():
            yield entry
