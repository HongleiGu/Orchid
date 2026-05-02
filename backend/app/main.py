from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.schemas import ErrorDetail, ErrorResponse
from app.config import get_settings

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

    # 2. Register bundled skills as RemoteSkill proxies. Every executable the
    #    LLM can call lives in skill-runner; the backend only holds proxies.
    from app.skills.bundled_loader import register_bundled_skills
    bundled_count = register_bundled_skills()
    logger.info("Registered %d bundled skills", bundled_count)

    # 3. Start WebSocket manager
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


# ── Error handling ────────────────────────────────────────────────────────────

@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=ErrorDetail(message=str(exc.detail))).model_dump(),
    )


@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error on %s %s", request.method, request.url)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(error=ErrorDetail(message="Internal server error")).model_dump(),
    )


# ── Routers ───────────────────────────────────────────────────────────────────

from app.api.v1 import agents, tasks, runs, providers, models as models_router, config, marketplace, budget, gmail, registry, vault as vault_router  # noqa: E402

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
app.include_router(vault_router.router, prefix=PREFIX)


@app.get("/health")
async def health():
    return {"status": "ok"}
