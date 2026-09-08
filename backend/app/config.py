from __future__ import annotations

import json
from functools import lru_cache
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

    # ── Access control ────────────────────────────────────────────────────────
    # These are the deployment capability ceiling and they live in config, not the
    # database, on purpose: every run consumes untrusted web content, so an agent
    # talked into misbehaving must have no write path to the thing restricting it.
    # Per-user entitlements layer on top and may only narrow this, never widen it.
    #
    # "full" = unrestricted (default, unchanged behaviour).
    # "app"  = locked-down run-only edition.
    product_profile: Literal["full", "app"] = "full"

    # Comma-separated API keys. Empty disables authentication, which is refused
    # outright when app_env is production.
    auth_api_keys: str = ""

    # Skill capability ceiling, mirroring n8n's NODES_INCLUDE / NODES_EXCLUDE.
    # allow empty  = no allowlist (subject to the denylist below)
    # deny applies always, and wins over allow.
    skills_allow: str = ""
    skills_deny: str = ""

    # Model ceiling. Empty = any model. Enforced before the LiteLLM call, so a
    # template cannot pin a model this deployment has not approved or paid for.
    models_allow: str = ""

    # ── Infrastructure ────────────────────────────────────────────────────────
    # Postgres only. SQLite was never really supported — there are no dialect
    # branches, alembic/env.py has no batch mode (so any ALTER/DROP migration
    # would fail on it), and nothing tested that path. Having the untested
    # dialect as the default just produced confusing "no such column" errors.
    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/agentapp"
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

    # ── LibLibAI (image generation) — deprecated, keep fields so old configs load
    liblib_access_key: str = ""
    liblib_secret_key: str = ""

    # ── Replicate (image generation) ─────────────────────────────────────────
    replicate_api_token: str = ""

    # ── Execution limits ──────────────────────────────────────────────────────
    scheduler_timezone: str = "UTC"
    scheduler_max_concurrent_runs: int = 5
    default_max_turns_per_agent: int = 5
    default_max_total_turns: int = 20
    # Runaway backstop for DAGs with loops: the total number of node executions
    # a single DAG run may perform across all iterations. Per-loop budgets live
    # on the loop-closing edge (`max_iterations`); this is the global ceiling.
    dag_max_total_node_executions: int = 100

    @property
    def cors_origins(self) -> list[str]:
        v = self.app_cors_origins.strip()
        if v.startswith("["):
            return json.loads(v)
        return [o.strip() for o in v.split(",") if o.strip()]

    # ── Access-control helpers ────────────────────────────────────────────────

    @property
    def api_keys(self) -> set[str]:
        return {k.strip() for k in self.auth_api_keys.split(",") if k.strip()}

    @property
    def auth_enabled(self) -> bool:
        return bool(self.api_keys)

    @property
    def skills_allowlist(self) -> set[str]:
        return {s.strip() for s in self.skills_allow.split(",") if s.strip()}

    @property
    def models_allowlist(self) -> set[str]:
        return {m.strip() for m in self.models_allow.split(",") if m.strip()}

    @property
    def skills_denylist(self) -> set[str]:
        """Explicit denies, plus the dangerous defaults when running locked down.

        n8n blocks its Execute Command node out of the box for the same reason:
        arbitrary command execution reachable from a workflow is not something a
        run-only deployment should offer, and opting in should be deliberate.
        """
        deny = {s.strip() for s in self.skills_deny.split(",") if s.strip()}
        if self.product_profile == "app":
            deny |= DEFAULT_DENIED_SKILLS - self.skills_allowlist
        return deny


# Denied by default in the "app" profile. An explicit entry in SKILLS_ALLOW
# overrides this, so a template that genuinely needs one can opt in.
DEFAULT_DENIED_SKILLS: set[str] = {
    "@orchid/workspace_exec",
    "@orchid/workspace_write",
    "@orchid/python_experiment",
}


@lru_cache
def get_settings() -> Settings:
    return Settings()
