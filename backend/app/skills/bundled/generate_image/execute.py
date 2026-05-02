from __future__ import annotations

import json
import os

import httpx


async def execute(prompt: str, size: str = "1024x1024", provider: str = "openai") -> str:
    try:
        if provider == "openai":
            url = await _openai(prompt, size)
        else:
            url = await _openrouter(prompt, size)
        return json.dumps({"type": "image", "url": url, "alt": prompt[:200]})
    except Exception as exc:
        return f"Image generation failed: {exc}"


async def _openai(prompt: str, size: str) -> str:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise ValueError("OPENAI_API_KEY is not set")
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            "https://api.openai.com/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "dall-e-3", "prompt": prompt, "n": 1, "size": size},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["url"]


async def _openrouter(prompt: str, size: str) -> str:
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")
    async with httpx.AsyncClient(timeout=90) as client:
        resp = await client.post(
            "https://openrouter.ai/api/v1/images/generations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": "openai/dall-e-3", "prompt": prompt, "n": 1, "size": size},
        )
        resp.raise_for_status()
        return resp.json()["data"][0]["url"]
