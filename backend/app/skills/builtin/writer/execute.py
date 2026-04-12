"""
Writer skill — transforms raw content into polished output.
Uses the default LLM for generation.
"""
from __future__ import annotations

_FORMAT_PROMPTS = {
    "blog": (
        "Write an engaging blog post. Include a compelling title, introduction that hooks the reader, "
        "clear sections with subheadings, and a conclusion. Use a conversational yet informative tone."
    ),
    "report": (
        "Write a structured report. Include an executive summary, clear sections with findings, "
        "analysis, and conclusions. Use formal language and cite sources where available."
    ),
    "email": (
        "Write a professional email. Be concise, clear, and actionable. "
        "Include a clear subject line suggestion at the top."
    ),
    "academic": (
        "Write in academic style. Use formal language, structured argumentation, "
        "proper citations format, and clear methodology description where applicable."
    ),
    "executive_summary": (
        "Write a concise executive summary. Lead with the key takeaway, "
        "follow with supporting points, and end with recommended actions. Keep it scannable."
    ),
    "general": (
        "Write clear, well-structured content. Use appropriate formatting with "
        "headers, paragraphs, and emphasis where needed."
    ),
}

_TONE_HINTS = {
    "professional": "Maintain a professional, authoritative voice.",
    "casual": "Use a friendly, approachable tone. It's okay to be conversational.",
    "technical": "Be precise and technical. Assume the reader has domain expertise.",
    "persuasive": "Build a compelling argument. Use evidence and rhetorical techniques.",
    "neutral": "Stay objective and balanced. Present multiple perspectives where relevant.",
}


async def execute(
    content: str,
    format: str = "general",
    tone: str = "professional",
    max_words: int = 1000,
    instructions: str = "",
) -> str:
    from app.models.client import model_client
    from app.config import get_settings

    model = get_settings().llm_default_model
    format_prompt = _FORMAT_PROMPTS.get(format, _FORMAT_PROMPTS["general"])
    tone_hint = _TONE_HINTS.get(tone, _TONE_HINTS["professional"])

    system = (
        f"You are a skilled writer. {format_prompt} {tone_hint}\n\n"
        f"Target length: approximately {max_words} words.\n"
        "Use markdown formatting. Output ONLY the final written content — no meta-commentary."
    )
    if instructions:
        system += f"\n\nAdditional instructions: {instructions}"

    user_msg = f"Transform the following into polished written content:\n\n{content}"

    response = await model_client.complete(
        model=model,
        system=system,
        history=[],
        tools=[],
        user_message=user_msg,
    )
    return response.content
