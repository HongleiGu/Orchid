from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Local dev: .env lives at project root (../.env from backend/)
        # Docker: env vars injected by docker-compose, no file needed
        env_file=("../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── App ──────────────────────────────────────────────────────────────────
    app_env: Literal["development", "production"] = "development"
    app_log_level: str = "INFO"
    app_cors_origins: str = "http://localhost:3000"  # comma-separated or JSON array

    # ── Infrastructure ────────────────────────────────────────────────────────
    database_url: str = "sqlite+aiosqlite:///./agentapp.db"
    redis_url: str = ""  # empty = in-process fallback

    # ── LLM ───────────────────────────────────────────────────────────────────
    llm_default_model: str = "openai/gpt-4o-mini"
    llm_fallback_model: str = ""

    # LiteLLM settings
    litellm_drop_params: bool = True
    litellm_request_timeout: int = 120
    litellm_max_retries: int = 3

    # ── Provider keys (LiteLLM picks these up automatically) ─────────────────
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    openai_api_base: str = ""
    groq_api_key: str = ""
    openrouter_api_key: str = ""
    ollama_api_base: str = "http://localhost:11434"

    # ── WeChat Official Account ─────────────────────────────────────────────
    wechat_app_id: str = ""
    wechat_app_secret: str = ""

    # ── Gmail OAuth ───────────────────────────────────────────────────────────
    gmail_client_id: str = ""
    gmail_client_secret: str = ""

    # ── Academic APIs ──────────────────────────────────────────────────────────
    semantic_scholar_api_key: str = ""
    openalex_api_key: str = ""

    # ── Tools ─────────────────────────────────────────────────────────────────
    search_provider: str = "tavily"
    tavily_api_key: str = ""
    serpapi_api_key: str = ""
    brave_api_key: str = ""

    # ── Execution limits ──────────────────────────────────────────────────────
    scheduler_timezone: str = "UTC"
    scheduler_max_concurrent_runs: int = 5
    default_max_turns_per_agent: int = 5
    default_max_total_turns: int = 20

    # ── Extension dirs ────────────────────────────────────────────────────────
    extra_skills_dir: Path | None = None
    mcp_config_path: Path | None = None

    @property
    def cors_origins(self) -> list[str]:
        v = self.app_cors_origins.strip()
        if v.startswith("["):
            return json.loads(v)
        return [o.strip() for o in v.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
