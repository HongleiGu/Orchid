"""
Image generation tool — supports multiple providers.

Returns a JSON content block: {"type": "image", "url": "...", "alt": "..."}
which the frontend ContentRenderer displays as an <img>.
"""
from __future__ import annotations

import json
import logging

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)


class GenerateImageTool(BaseTool):
    name = "@orchid/generate_image"
    description = (
        "Generate an image from a text prompt. Returns a viewable image. "
        "Use descriptive, detailed prompts for best results."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Detailed description of the image to generate.",
            },
            "size": {
                "type": "string",
                "enum": ["1024x1024", "1024x1792", "1792x1024"],
                "default": "1024x1024",
                "description": "Image dimensions.",
            },
            "provider": {
                "type": "string",
                "enum": ["openai", "openrouter"],
                "default": "openai",
                "description": "Which provider to use for generation.",
            },
        },
        "required": ["prompt"],
    }

    async def call(
        self,
        prompt: str,
        size: str = "1024x1024",
        provider: str = "openai",
    ) -> str:
        try:
            if provider == "openai":
                url = await self._openai(prompt, size)
            else:
                url = await self._openrouter(prompt, size)

            return json.dumps({
                "type": "image",
                "url": url,
                "alt": prompt[:200],
            })
        except Exception as exc:
            logger.error("Image generation failed: %s", exc)
            return f"Image generation failed: {exc}"

    async def _openai(self, prompt: str, size: str) -> str:
        from app.config import get_settings
        import httpx

        api_key = get_settings().openai_api_key
        if not api_key:
            raise ValueError("OPENAI_API_KEY is not set")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "dall-e-3",
                    "prompt": prompt,
                    "n": 1,
                    "size": size,
                },
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["url"]

    async def _openrouter(self, prompt: str, size: str) -> str:
        from app.config import get_settings
        import httpx

        api_key = get_settings().openrouter_api_key
        if not api_key:
            raise ValueError("OPENROUTER_API_KEY is not set")

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                "https://openrouter.ai/api/v1/images/generations",
                headers={"Authorization": f"Bearer {api_key}"},
                json={
                    "model": "openai/dall-e-3",
                    "prompt": prompt,
                    "n": 1,
                    "size": size,
                },
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["url"]
