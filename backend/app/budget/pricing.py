"""
Model pricing table — cost per 1M tokens (input / output) in USD.
Prices as of early 2026. Update as needed.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass


logger = logging.getLogger(__name__)


@dataclass
class ModelPricing:
    input_per_m: float   # USD per 1M input tokens
    output_per_m: float  # USD per 1M output tokens


# Key = model ID as used in LiteLLM (prefix/model)
_PRICING: dict[str, ModelPricing] = {
    # Anthropic — Opus 4.7 is reserved for the most demanding cases (high-stakes
    # judges, final reports). Default workflows should select Sonnet 4.6.
    "anthropic/claude-opus-4-7":   ModelPricing(15.0, 75.0),
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
    "openrouter/anthropic/claude-opus-4-7":       ModelPricing(15.0, 75.0),
    "openrouter/anthropic/claude-opus-4-6":       ModelPricing(15.0, 75.0),
    "openrouter/anthropic/claude-sonnet-4-6":     ModelPricing(3.0, 15.0),
    "openrouter/anthropic/claude-sonnet-4":       ModelPricing(3.0, 15.0),
    "openrouter/google/gemini-2.0-flash-001":      ModelPricing(0.10, 0.40),
    "openrouter/google/gemini-2.5-flash-preview":  ModelPricing(0.15, 0.60),
    "openrouter/meta-llama/llama-3.3-70b-instruct": ModelPricing(0.40, 0.40),
    "openrouter/deepseek/deepseek-v4-flash":       ModelPricing(0.20, 0.80),
    "openrouter/deepseek/deepseek-chat-v3-0324":   ModelPricing(0.27, 1.10),
    "openrouter/qwen/qwen-2.5-72b-instruct":      ModelPricing(0.30, 0.30),
    # Groq (free tier / very cheap)
    "groq/llama-3.3-70b-versatile": ModelPricing(0.59, 0.79),
    "groq/llama-3.1-8b-instant":   ModelPricing(0.05, 0.08),
    # DeepSeek, called directly rather than through OpenRouter. Mirrors the
    # openrouter/deepseek/deepseek-chat-v3-0324 entry above. VERIFY against
    # DeepSeek's current price list before trusting billing numbers — these
    # are carried over, not confirmed, and DeepSeek has repriced before.
    "deepseek/deepseek-chat":      ModelPricing(0.27, 1.10),
    "deepseek/deepseek-reasoner":  ModelPricing(0.55, 2.19),
}

# Fallback for unknown models. Deliberately expensive: a cost that reads too
# high prompts someone to add the model, whereas one that reads too low is
# discovered on an invoice.
_DEFAULT = ModelPricing(1.0, 3.0)

# Models already reported as unpriced, so the warning fires once each rather
# than on every call in a run.
_warned_unknown: set[str] = set()


def is_priced(model: str) -> bool:
    return model in _PRICING


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate cost in USD for a single LLM call.

    An unlisted model silently falls back, and the gap can be large — DeepSeek
    is roughly 50x cheaper than the fallback, so a run would report cents as
    dollars. Now that per-run cost is surfaced in the API, log it once so the
    number is known to be an estimate rather than quietly wrong.
    """
    pricing = _PRICING.get(model)
    if pricing is None:
        pricing = _DEFAULT
        if model not in _warned_unknown:
            _warned_unknown.add(model)
            logger.warning(
                "No pricing for model %r — using the $%.2f/$%.2f per-Mtok fallback. "
                "Reported costs for this model are estimates. Add it to _PRICING.",
                model, _DEFAULT.input_per_m, _DEFAULT.output_per_m,
            )
    cost = (input_tokens * pricing.input_per_m + output_tokens * pricing.output_per_m) / 1_000_000
    return round(cost, 6)


def get_pricing_table() -> dict[str, ModelPricing]:
    return dict(_PRICING)
