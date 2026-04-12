"""
Text-to-speech tool — generates audio from text.

Returns a JSON content block: {"type": "audio", "url": "...", "format": "mp3"}
which the frontend ContentRenderer displays as an <audio> player.

Uses OpenAI's TTS API (or OpenRouter passthrough).
"""
from __future__ import annotations

import base64
import json
import logging
import tempfile
from pathlib import Path

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class TextToSpeechTool(BaseTool):
    name = "@orchid/text_to_speech"
    description = (
        "Convert text to speech audio. Returns a playable audio file. "
        "Best for short to medium-length text (under 4000 characters)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "text": {
                "type": "string",
                "description": "The text to convert to speech.",
            },
            "voice": {
                "type": "string",
                "enum": ["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                "default": "nova",
                "description": "Voice style to use.",
            },
            "speed": {
                "type": "number",
                "default": 1.0,
                "description": "Playback speed (0.25 to 4.0).",
            },
        },
        "required": ["text"],
    }

    async def call(
        self,
        text: str,
        voice: str = "nova",
        speed: float = 1.0,
    ) -> str:
        try:
            url = await self._generate(text, voice, speed)
            return json.dumps({
                "type": "audio",
                "url": url,
                "format": "mp3",
            })
        except Exception as exc:
            logger.error("TTS failed: %s", exc)
            return f"Text-to-speech failed: {exc}"

    async def _generate(self, text: str, voice: str, speed: float) -> str:
        from app.config import get_settings
        import httpx

        api_key = get_settings().openai_api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set — required for TTS")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "tts-1",
                    "input": text[:4096],
                    "voice": voice,
                    "speed": max(0.25, min(4.0, speed)),
                    "response_format": "mp3",
                },
            )
            resp.raise_for_status()

        # Return as base64 data URL (avoids needing file hosting)
        audio_b64 = base64.b64encode(resp.content).decode("ascii")
        return f"data:audio/mp3;base64,{audio_b64}"
