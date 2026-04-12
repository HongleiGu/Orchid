from __future__ import annotations


async def execute(text: str, max_words: int = 150) -> str:
    """Summarize text using the default LLM."""
    from app.models.client import model_client
    from app.config import get_settings

    model = get_settings().llm_default_model
    prompt = (
        f"Summarize the following text in at most {max_words} words. "
        "Be concise and preserve the key facts.\n\n"
        f"{text}"
    )
    response = await model_client.complete(
        model=model,
        system="You are a precise summarization assistant.",
        history=[],
        tools=[],
        user_message=prompt,
    )
    return response.content
