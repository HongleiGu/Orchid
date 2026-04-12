"""
Model pricing table — cost per 1M tokens (input / output) in USD.
Prices as of early 2026. Update as needed.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ModelPricing:
    input_per_m: float   # USD per 1M input tokens
    output_per_m: float  # USD per 1M output tokens


# Key = model ID as used in LiteLLM (prefix/model)
_PRICING: dict[str, ModelPricing] = {
    # Anthropic
    "anthropic/claude-opus-4-6":   ModelPricing(15.0, 75.0),
    "anthropic/claude-sonnet-4-6": ModelPricing(3.0, 15.0),
    "anthropic/claude-haiku-4-5-20251001": ModelPricing(0.80, 4.0),
    # OpenAI
    "openai/gpt-4o":               ModelPricing(2.50, 10.0),
    "openai/gpt-4o-mini":          ModelPricing(0.15, 0.60),
    "openai/o3-mini":              ModelPricing(1.10, 4.40),
    # OpenRouter (same models, same pricing — OpenRouter adds ~0% markup for most)
    "openrouter/openai/gpt-4o-mini":              ModelPricing(0.15, 0.60),
    "openrouter/openai/gpt-4o":                   ModelPricing(2.50, 10.0),
    "openrouter/anthropic/claude-opus-4.6":        ModelPricing(5.0, 25.0),
    "openrouter/anthropic/claude-sonnet-4.6":        ModelPricing(3.0, 15.0),
    "openrouter/google/gemini-2.0-flash-001":      ModelPricing(0.10, 0.40),
    "openrouter/google/gemini-2.5-flash-preview":  ModelPricing(0.15, 0.60),
    "openrouter/meta-llama/llama-3.3-70b-instruct": ModelPricing(0.40, 0.40),
    "openrouter/deepseek/deepseek-chat-v3-0324":   ModelPricing(0.27, 1.10),
    "openrouter/qwen/qwen-2.5-72b-instruct":      ModelPricing(0.30, 0.30),
    # Groq (free tier / very cheap)
    "groq/llama-3.3-70b-versatile": ModelPricing(0.59, 0.79),
    "groq/llama-3.1-8b-instant":   ModelPricing(0.05, 0.08),
}

# Fallback for unknown models
_DEFAULT = ModelPricing(1.0, 3.0)


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a single LLM call."""
    pricing = _PRICING.get(model, _DEFAULT)
    cost = (input_tokens * pricing.input_per_m + output_tokens * pricing.output_per_m) / 1_000_000
    return round(cost, 6)


def get_pricing_table() -> dict[str, ModelPricing]:
    return dict(_PRICING)
