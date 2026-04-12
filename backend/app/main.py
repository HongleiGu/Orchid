from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

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

    # 1. Create DB tables (dev) — use Alembic in production
    from app.db.base import Base
    from app.db.session import engine
    import app.db.models  # noqa: F401 — ensure models are registered

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Register built-in tools
    from app.tools.registry import tool_registry
    from app.tools.builtin.web_search import WebSearchTool
    from app.tools.builtin.http_request import HttpRequestTool
    from app.tools.builtin.generate_image import GenerateImageTool
    from app.tools.builtin.text_to_speech import TextToSpeechTool
    from app.tools.builtin.wechat import WeChatPublishTool, WeChatFollowersTool
    from app.tools.builtin.gmail import GmailSendTool, GmailReadTool

    tool_registry.register(WebSearchTool())
    tool_registry.register(HttpRequestTool())
    tool_registry.register(GenerateImageTool())
    tool_registry.register(TextToSpeechTool())
    tool_registry.register(WeChatPublishTool())
    tool_registry.register(WeChatFollowersTool())
    tool_registry.register(GmailSendTool())
    tool_registry.register(GmailReadTool())

    from app.tools.builtin.vault import VaultWriteTool, VaultReadTool, VaultSearchTool
    tool_registry.register(VaultWriteTool())
    tool_registry.register(VaultReadTool())
    tool_registry.register(VaultSearchTool())

    # 3. Load built-in skills
    from app.skills.registry import skill_registry

    builtin_skills_dir = Path(__file__).parent / "skills" / "builtin"
    skill_registry.load_from_dir(builtin_skills_dir, prefix="@orchid/")

    if settings.extra_skills_dir:
        skill_registry.load_from_dir(settings.extra_skills_dir, prefix="@orchid/")

    # 4. Register bundled skills (run in skill-runner sandbox, proxied via HTTP)
    from app.skills.bundled_loader import register_bundled_skills
    bundled_count = register_bundled_skills()
    logger.info("Registered %d bundled skills", bundled_count)

    # 6. Load MCP servers (if configured)
    if settings.mcp_config_path:
        from app.mcp.registry import load_mcp_servers
        await load_mcp_servers(settings.mcp_config_path)

    # 7. Start WebSocket manager
    from app.ws.manager import ws_manager
    await ws_manager.startup()

    # 8. Start scheduler
    from app.scheduler.service import startup as scheduler_startup
    await scheduler_startup()

    # 9. Re-register marketplace proxies from DB
    from app.marketplace.service import marketplace
    from app.db.session import AsyncSessionLocal
    async with AsyncSessionLocal() as db:
        await marketplace.register_all_from_db(db)

    logger.info("Backend started — env=%s", settings.app_env)
    yield

    # ── Shutdown ──────────────────────────────────────────────────────────────
    from app.scheduler.service import shutdown as scheduler_shutdown
    await scheduler_shutdown()

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
