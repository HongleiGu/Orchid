from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.api.schemas import DataResponse

router = APIRouter(prefix="/providers", tags=["providers"])


class ProviderOut(BaseModel):
    name: str
    key_set: bool
    base_url: str
    reachable: bool | None = None


class SecretOut(BaseModel):
    key: str
    is_set: bool
    masked: str  # e.g. "sk-ant-...ngAA"


class SecretUpdate(BaseModel):
    key: str
    value: str


@router.get("", response_model=DataResponse[list[ProviderOut]])
async def list_providers():
    from app.models.registry import get_providers
    providers = get_providers()
    return DataResponse(data=[
        ProviderOut(name=p.name, key_set=p.key_set, base_url=p.base_url)
        for p in providers
    ])


# ── Secrets management (reads/writes the .env file) ──────────────────────────

_SECRET_KEYS = [
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "OPENAI_API_BASE",
    "GROQ_API_KEY",
    "OPENROUTER_API_KEY",
    "TAVILY_API_KEY",
    "SERPAPI_API_KEY",
    "BRAVE_API_KEY",
    "WECHAT_APP_ID",
    "WECHAT_APP_SECRET",
    "GMAIL_CLIENT_ID",
    "GMAIL_CLIENT_SECRET",
    "SEMANTIC_SCHOLAR_API_KEY",
    "OPENALEX_API_KEY",
    "LLM_DEFAULT_MODEL",
]


def _find_env_path() -> Path:
    """Walk up from cwd to find the .env file."""
    for candidate in [
        Path(".env"),
        Path("../.env"),
        Path("../../.env"),
    ]:
        resolved = candidate.resolve()
        if resolved.exists():
            return resolved
    raise FileNotFoundError("Could not locate .env file")


def _mask(value: str) -> str:
    if not value or len(value) < 8:
        return "*" * len(value)
    return value[:6] + "…" + value[-4:]


def _read_env(path: Path) -> dict[str, str]:
    """Parse .env into a dict (handles comments and blank lines)."""
    result: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" in stripped:
            key, _, value = stripped.partition("=")
            result[key.strip()] = value.strip()
    return result


def _write_env(path: Path, updates: dict[str, str]) -> None:
    """Update specific keys in the .env file, preserving structure."""
    lines = path.read_text(encoding="utf-8").splitlines()
    updated_keys: set[str] = set()
    new_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                updated_keys.add(key)
                continue
        new_lines.append(line)

    # Append any keys that weren't already in the file
    for key, value in updates.items():
        if key not in updated_keys:
            new_lines.append(f"{key}={value}")

    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


@router.get("/secrets", response_model=DataResponse[list[SecretOut]])
async def list_secrets():
    try:
        env_path = _find_env_path()
        env = _read_env(env_path)
    except FileNotFoundError:
        env = {}

    secrets = []
    for key in _SECRET_KEYS:
        val = env.get(key, "")
        secrets.append(SecretOut(
            key=key,
            is_set=bool(val),
            masked=_mask(val) if val else "",
        ))
    return DataResponse(data=secrets)


@router.put("/secrets", response_model=DataResponse[list[SecretOut]])
async def update_secrets(body: list[SecretUpdate]):
    try:
        env_path = _find_env_path()
    except FileNotFoundError:
        raise HTTPException(500, "Could not locate .env file")

    # Only allow updating known keys
    updates: dict[str, str] = {}
    for item in body:
        if item.key in _SECRET_KEYS:
            updates[item.key] = item.value

    if updates:
        _write_env(env_path, updates)

        # Clear the cached settings so changes take effect
        from app.config import get_settings
        get_settings.cache_clear()

    # Return updated state
    env = _read_env(env_path)
    secrets = []
    for key in _SECRET_KEYS:
        val = env.get(key, "")
        secrets.append(SecretOut(
            key=key,
            is_set=bool(val),
            masked=_mask(val) if val else "",
        ))
    return DataResponse(data=secrets)
