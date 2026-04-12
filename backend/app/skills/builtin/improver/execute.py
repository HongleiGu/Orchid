"""
Self-improving content refiner.

Each pass:
  1. Critique: evaluate against criteria, list specific weaknesses
  2. Rewrite: address each weakness, preserve strengths

Inspired by ClaWHub pskoett/self-improving-agent.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_DEFAULT_CRITERIA = (
    "1. Accuracy — are claims correct and supported?\n"
    "2. Clarity — is the writing easy to follow?\n"
    "3. Completeness — are there gaps or missing context?\n"
    "4. Structure — is it well-organized with clear flow?\n"
    "5. Engagement — does it hold the reader's attention?\n"
    "6. Conciseness — is there unnecessary repetition or filler?"
)


async def execute(
    content: str,
    criteria: str = "",
    passes: int = 2,
    focus: str = "",
) -> str:
    from app.models.client import model_client
    from app.config import get_settings

    model = get_settings().llm_default_model
    passes = max(1, min(passes, 3))
    eval_criteria = criteria or _DEFAULT_CRITERIA

    current = content
    critique_log: list[str] = []

    for i in range(passes):
        logger.info("Improvement pass %d/%d", i + 1, passes)

        # ── Step 1: Critique ─────────────────────────────────────────────
        critique_system = (
            "You are a rigorous editor and critic. Evaluate the content against these criteria:\n\n"
            f"{eval_criteria}\n\n"
            "For each criterion, give a score (1-5) and list SPECIFIC weaknesses with line-level detail.\n"
            "Be constructive but honest. Don't praise — focus on what needs improvement.\n"
            "End with a prioritized list of the top 3 changes that would most improve the content."
        )
        if focus:
            critique_system += f"\n\nPay special attention to: {focus}"

        critique_response = await model_client.complete(
            model=model,
            system=critique_system,
            history=[],
            tools=[],
            user_message=f"Critique this content:\n\n{current}",
        )
        critique = critique_response.content
        critique_log.append(f"### Pass {i + 1} Critique\n{critique}")

        # ── Step 2: Rewrite ──────────────────────────────────────────────
        rewrite_system = (
            "You are a skilled rewriter. You will receive content and a critique of that content.\n"
            "Rewrite the content to address EVERY weakness identified in the critique.\n"
            "Preserve the strengths and overall structure unless the critique says otherwise.\n"
            "Output ONLY the improved content — no meta-commentary, no 'here is the improved version'."
        )
        if focus:
            rewrite_system += f"\n\nPrimary focus for this rewrite: {focus}"

        rewrite_msg = (
            f"## Original Content\n{current}\n\n"
            f"## Critique\n{critique}\n\n"
            "Rewrite the content addressing all identified weaknesses."
        )
        rewrite_response = await model_client.complete(
            model=model,
            system=rewrite_system,
            history=[],
            tools=[],
            user_message=rewrite_msg,
        )
        current = rewrite_response.content

    # Return improved content with critique log appended as a hidden section
    result = current
    if len(critique_log) > 0:
        result += "\n\n<!--\n## Improvement Log\n"
        result += "\n\n".join(critique_log)
        result += "\n-->"

    return result
