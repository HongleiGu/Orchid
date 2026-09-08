from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.schemas import ErrorDetail, ErrorResponse
from app.config import get_settings
from app.skills.registry import SkillNotPermitted

logger = logging.getLogger(__name__)
settings = get_settings()


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ───────────────────────────────────────────────────────────────
    logging.basicConfig(level=settings.app_log_level)

    # 1. Register ORM models. Schema is managed by Alembic — migrations run
    #    in the docker entrypoint before this process starts. For local dev,
    #    run `alembic upgrade head` manually.
    import app.db.models  # noqa: F401
    from app.db.session import engine  # imported here so it's available on shutdown

    from app.db.schema_check import warn_if_schema_is_stale
    await warn_if_schema_is_stale(engine)

    #    Fail fast rather than serving an unauthenticated API in production.
    #    After the DB is available: a deployment may authenticate entirely
    #    with issued keys and no static AUTH_API_KEYS at all.
    from app.auth.api_key import verify_startup_configuration
    await verify_startup_configuration()

    # 2. Register bundled skills as RemoteSkill proxies. Every executable the
    #    LLM can call lives in skill-runner; the backend only holds proxies.
    from app.skills.bundled_loader import register_bundled_skills
    bundled_count = register_bundled_skills()
    logger.info("Registered %d bundled skills", bundled_count)

    #    Templates are the curated workflows a run-only edition offers. They
    #    ship as files with the release, so there is no write surface.
    from app.templates.registry import load_templates
    load_templates()

    #    Subscription tiers. Config, not database: a plan may only narrow the
    #    deployment ceiling, never widen it.
    from app.plans.registry import load_plans
    load_plans()

    #    Attestation text. Config for the same reason, and one more: an agent
    #    that has read untrusted web content must have no path to rewriting
    #    what users are asked to agree to.
    from app.attestations.registry import load_attestations
    load_attestations()

    # 3. Start the run-event broker
    from app.ws.manager import ws_manager
    await ws_manager.startup()

    # 4. Start the run consumer (single sequential queue worker).
    #    Also recovers any runs left in `running` from a previous crash.
    from app.executor.run_executor import start_consumer
    await start_consumer()

    # 5. Start scheduler
    from app.scheduler.service import startup as scheduler_startup
    await scheduler_startup()

    # 6. Re-register marketplace proxies from DB
    from app.marketplace.service import marketplace
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await marketplace.register_all_from_db(db)

    logger.info("Backend started — env=%s", settings.app_env)
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    from app.scheduler.service import shutdown as scheduler_shutdown
    await scheduler_shutdown()

    from app.executor.run_executor import stop_consumer
    await stop_consumer()

    from app.ws.manager import ws_manager
    await ws_manager.shutdown()

    await engine.dispose()
    logger.info("Backend stopped")


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Orchid",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Authentication ────────────────────────────────────────────────────────────

@app.middleware("http")
async def api_key_middleware(request: Request, call_next):
    """Reject unauthenticated requests before they reach any route.

    OPTIONS is exempt because CORS preflight carries no credentials — the browser
    sends the real request, with the key, only once preflight succeeds.
    """
    from app.auth.api_key import auth_is_enforced, authenticate, extract_key, is_public_path

    if request.method == "OPTIONS" or is_public_path(request.url.path):
        return await call_next(request)

    # Not settings.auth_enabled, which sees only static keys: a deployment
    # holding nothing but issued keys would skip this check entirely and serve
    # the API anonymously.
    if not await auth_is_enforced():
        return await call_next(request)

    ok, user_id = await authenticate(extract_key(request))
    # Stashed so handlers can attribute work without re-authenticating. None is
    # a legitimate value (static key), so handlers must treat it as "unknown
    # user", not "not set".
    request.state.user_id = user_id
    if not ok:
        return JSONResponse(
            status_code=401,
            content=ErrorResponse(
                error=ErrorDetail(message="Missing or invalid API key")
            ).model_dump(),
            headers={"WWW-Authenticate": "Bearer"},
        )

    return await call_next(request)


@app.middleware("http")
async def product_profile_middleware(request: Request, call_next):
    """Refuse anything outside the allowlist when running the run-only profile.

    Ordering note: middleware added later runs first, so this executes before
    the auth check above. That is the wrong way round for information leakage —
    an unauthenticated caller learns which paths exist — so authentication is
    verified here too before refusing on profile grounds.
    """
    from app.auth.api_key import auth_is_enforced, authenticate, extract_key, is_public_path
    from app.auth.profile import is_request_permitted

    settings = get_settings()
    if (
        settings.product_profile != "app"
        or request.method == "OPTIONS"
        or is_public_path(request.url.path)
    ):
        return await call_next(request)

    authed, _ = await authenticate(extract_key(request))
    if await auth_is_enforced() and not authed:
        return await call_next(request)   # let the auth middleware return 401

    if not is_request_permitted(request.method, request.url.path):
        return JSONResponse(
            status_code=403,
            content=ErrorResponse(
                error=ErrorDetail(
                    message="Not available in this edition"
                )
            ).model_dump(),
        )

    return await call_next(request)


# ── Error handling ────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=ErrorDetail(message=str(exc.detail))).model_dump(),
    )


@app.exception_handler(SkillNotPermitted)
async def skill_not_permitted_handler(request: Request, exc: SkillNotPermitted):
    """Surface a blocked skill as 403 rather than a 500.

    Agents are not validated against the registry at creation time, so a denied
    skill is discovered when a run resolves it. That is the intended choke point
    — this handler just makes the failure legible.
    """
    return JSONResponse(
        status_code=403,
        content=ErrorResponse(error=ErrorDetail(message=str(exc))).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error=ErrorDetail(message="Internal server error")).model_dump(),
    )


# ── Routers ───────────────────────────────────────────────────────────────────

from app.api.v1 import agents, tasks, runs, providers, models as models_router, config, marketplace, budget, gmail, registry, skill_writer, workflow_maker, templates as templates_router, vault as vault_router, attestations as attestations_router  # noqa: E402

PREFIX = "/api/v1"
app.include_router(agents.router, prefix=PREFIX)
app.include_router(tasks.router, prefix=PREFIX)
app.include_router(runs.router, prefix=PREFIX)
app.include_router(providers.router, prefix=PREFIX)
app.include_router(models_router.router, prefix=PREFIX)
app.include_router(config.router, prefix=PREFIX)
app.include_router(marketplace.router, prefix=PREFIX)
app.include_router(budget.router, prefix=PREFIX)
app.include_router(gmail.router, prefix=PREFIX)
app.include_router(registry.router, prefix=PREFIX)
app.include_router(skill_writer.router, prefix=PREFIX)
app.include_router(workflow_maker.router, prefix=PREFIX)
app.include_router(templates_router.router, prefix=PREFIX)
app.include_router(vault_router.router, prefix=PREFIX)
app.include_router(attestations_router.router, prefix=PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok"}
