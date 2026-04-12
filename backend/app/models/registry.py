"""
Static registry of known models and providers.
Extend this list as new models are released.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config import get_settings


@dataclass
class ModelInfo:
    id: str           # LiteLLM model id, e.g. "anthropic/claude-sonnet-4-6"
    provider: str
    tools: bool
    vision: bool
    context: int      # context window (tokens)
    output_tokens: int


@dataclass
class ProviderInfo:
    name: str
    key_env: str      # env var name that holds the API key
    base_url: str
    key_set: bool = False
    reachable: bool | None = None


_MODELS: list[ModelInfo] = [
    # Anthropic
    ModelInfo("anthropic/claude-opus-4-6",    "anthropic", True, True, 200_000, 32_000),
    ModelInfo("anthropic/claude-sonnet-4-6",  "anthropic", True, True, 200_000, 16_000),
    ModelInfo("anthropic/claude-haiku-4-5-20251001",  "anthropic", True, True, 200_000,  8_192),
    # OpenAI
    ModelInfo("openai/gpt-4o",                "openai",    True, True, 128_000,  4_096),
    ModelInfo("openai/gpt-4o-mini",           "openai",    True, True, 128_000,  4_096),
    ModelInfo("openai/o3-mini",               "openai",    False, False, 200_000, 100_000),
    # Groq
    ModelInfo("groq/llama-3.3-70b-versatile", "groq",      True, False, 128_000,  8_000),
    ModelInfo("groq/llama-3.1-8b-instant",    "groq",      True, False, 128_000,  8_000),
    # OpenRouter (passthrough — model IDs are prefixed with openrouter/)
    ModelInfo("openrouter/google/gemini-2.0-flash-001",     "openrouter", True,  True,  1_048_576,  8_192),
    ModelInfo("openrouter/google/gemini-2.5-flash-preview", "openrouter", True,  True,  1_048_576,  8_192),
    ModelInfo("openrouter/openai/gpt-4o-mini",              "openrouter", True,  True,    128_000,  4_096),
    ModelInfo("openrouter/openai/gpt-4o",                   "openrouter", True,  True,    128_000,  4_096),
    ModelInfo("openrouter/anthropic/claude-sonnet-4",       "openrouter", True,  True,    200_000, 16_000),
    ModelInfo("openrouter/meta-llama/llama-3.3-70b-instruct","openrouter", True, False,  128_000,  8_000),
    ModelInfo("openrouter/deepseek/deepseek-chat-v3-0324",  "openrouter", True,  False,  128_000,  8_000),
    ModelInfo("openrouter/qwen/qwen-2.5-72b-instruct",     "openrouter", True,  False,  128_000,  8_000),
]

_PROVIDERS: list[ProviderInfo] = [
    ProviderInfo("anthropic",   "ANTHROPIC_API_KEY",   "https://api.anthropic.com"),
    ProviderInfo("openai",      "OPENAI_API_KEY",      "https://api.openai.com"),
    ProviderInfo("groq",        "GROQ_API_KEY",        "https://api.groq.com"),
    ProviderInfo("openrouter",  "OPENROUTER_API_KEY",  "https://openrouter.ai/api/v1"),
    ProviderInfo("ollama",      "",                    "http://localhost:11434"),
]


def get_models() -> list[ModelInfo]:
    return list(_MODELS)


def get_providers() -> list[ProviderInfo]:
    s = get_settings()
    key_map = {
        "anthropic":  s.anthropic_api_key,
        "openai":     s.openai_api_key,
        "groq":       s.groq_api_key,
        "openrouter": s.openrouter_api_key,
        "ollama":     "no-key-needed",
    }
    result = []
    for p in _PROVIDERS:
        key_value = key_map.get(p.name, "")
        result.append(
            ProviderInfo(
                name=p.name,
                key_env=p.key_env,
                base_url=p.base_url,
                key_set=bool(key_value),
            )
        )
    return result
