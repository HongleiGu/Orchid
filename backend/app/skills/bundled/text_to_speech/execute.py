from __future__ import annotations

import base64
import json
import os

import httpx


async def execute(text: str, voice: str = "nova", speed: float = 1.0) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        return "Text-to-speech failed: OPENAI_API_KEY is not set"

    try:
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

        audio_b64 = base64.b64encode(resp.content).decode("ascii")
        return json.dumps({
            "type": "audio",
            "url": f"data:audio/mp3;base64,{audio_b64}",
            "format": "mp3",
        })
    except Exception as exc:
        return f"Text-to-speech failed: {exc}"
