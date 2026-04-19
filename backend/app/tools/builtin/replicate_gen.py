"""
Replicate image generation — multi-image sequential models (Seedream etc.).

Key difference from the old LibLib tool: a SINGLE prompt containing
"Scene 1: ... Scene 2: ... Scene N: ..." generates N visually-consistent
images in one call (via `sequential_image_generation: "auto"`). No polling
logic needed — the SDK handles it.

Credentials: REPLICATE_API_TOKEN in .env.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

VAULT_DIR = Path(os.environ.get("VAULT_DIR", "/app/vault"))

_DEFAULT_MODEL = "bytedance/seedream-5-lite"


class ReplicateGenerateImagesTool(BaseTool):
    name = "@orchid/replicate_generate_images"
    description = (
        "Multiple style-consistent images sharing one character/aesthetic — use for "
        "storyboards, story scenes, comic panels. Format the prompt as "
        "'<shared style + character>. Scene 1: ...\\nScene 2: ...'. "
        "For one-off images use generate_image."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": (
                    "Single combined prompt. Recommended shape: "
                    "'<style + character description>. Maintain consistent character "
                    "design, art style, and color palette across all images.\\n"
                    "Scene 1: ...\\nScene 2: ...\\n...'"
                ),
            },
            "max_images": {
                "type": "integer",
                "default": 4,
                "description": "How many scenes/images to generate in this call.",
            },
            "aspect_ratio": {
                "type": "string",
                "default": "2:3",
                "description": "'1:1', '2:3', '3:2', '16:9', '9:16', etc.",
            },
            "size": {
                "type": "string",
                "default": "2K",
                "description": "'1K' or '2K' (model-specific; higher = slower + more cost).",
            },
            "output_format": {
                "type": "string",
                "default": "png",
                "description": "'png', 'jpg', or 'webp'.",
            },
            "sequential_image_generation": {
                "type": "string",
                "default": "auto",
                "description": "'auto' = model enforces cross-image consistency. 'disabled' = independent generations.",
            },
            "model": {
                "type": "string",
                "default": _DEFAULT_MODEL,
                "description": "Replicate model reference (e.g. 'bytedance/seedream-5-lite' or 'owner/name:version').",
            },
            "vault_project": {
                "type": "string",
                "default": "bedtime-stories",
                "description": "Vault subfolder to save images in.",
            },
            "filename_prefix": {
                "type": "string",
                "default": "",
                "description": "Filename stem (auto timestamp+slug if empty). Per-image suffix '-scene-N.ext' is appended.",
            },
        },
        "required": ["prompt"],
    }

    async def call(
        self,
        prompt: str,
        max_images: int = 4,
        aspect_ratio: str = "2:3",
        size: str = "2K",
        output_format: str = "png",
        sequential_image_generation: str = "auto",
        model: str = _DEFAULT_MODEL,
        vault_project: str = "bedtime-stories",
        filename_prefix: str = "",
    ) -> str:
        from app.config import get_settings
        s = get_settings()
        if not s.replicate_api_token:
            return "Error: REPLICATE_API_TOKEN not set in .env"

        try:
            import replicate
        except ImportError:
            return "Error: `replicate` package not installed. Run pip install replicate."

        # Set token via env (SDK reads REPLICATE_API_TOKEN). Scoping it to the
        # call avoids polluting process-wide state if tests or other tools run.
        os.environ["REPLICATE_API_TOKEN"] = s.replicate_api_token

        input_payload = {
            "prompt": prompt,
            "image_input": [],
            "max_images": max_images,
            "aspect_ratio": aspect_ratio,
            "size": size,
            "output_format": output_format,
            "sequential_image_generation": sequential_image_generation,
        }

        try:
            output = await replicate.async_run(model, input=input_payload)
        except Exception as exc:
            logger.exception("Replicate run failed")
            return f"Replicate generation failed: {exc}"

        try:
            items = await _collect_items(output)
        except Exception as exc:
            logger.exception("Replicate output collection failed")
            return f"Replicate output collection failed ({type(output).__name__}): {exc}"

        logger.info(
            "Replicate output: outer=%s count=%d first_type=%s",
            type(output).__name__, len(items),
            type(items[0]).__name__ if items else "N/A",
        )
        if not items:
            return f"Replicate returned no images. Raw output type: {type(output).__name__}."

        project_safe = _sanitize(vault_project)
        assets_dir = VAULT_DIR / project_safe / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)

        if not filename_prefix:
            filename_prefix = datetime.now(timezone.utc).strftime("story-%Y%m%d-%H%M%S")
        filename_prefix = _sanitize(filename_prefix)

        saved: list[dict] = []
        errors: list[str] = []
        for i, item in enumerate(items):
            try:
                data, url = await _extract_bytes_and_url(item)
            except Exception as exc:
                msg = f"item {i}: {type(item).__name__} → {type(exc).__name__}: {exc}"
                logger.warning("Replicate item read failed — %s", msg)
                errors.append(msg)
                continue

            filename = f"{filename_prefix}-scene-{i + 1}.{output_format}"
            target = assets_dir / filename
            target.write_bytes(data)

            saved.append({
                "index": i + 1,
                "vault_path": f"{project_safe}/assets/{filename}",
                "remote_url": url,
            })

        result: dict = {"count": len(saved), "model": model, "images": saved}
        if errors:
            result["errors"] = errors
        return json.dumps(result)


# ── Output shape handling ─────────────────────────────────────────────────────

async def _collect_items(output) -> list:
    """Normalise whatever Replicate returned into a flat list of items.
    Handles: list, sync iterator, async iterator, single item, dict with 'images' key.
    """
    if output is None:
        return []
    if isinstance(output, (list, tuple)):
        return list(output)
    if isinstance(output, dict):
        # Some models wrap output, e.g. {"images": [...]} or {"output": [...]}.
        for key in ("images", "output", "results", "urls"):
            if key in output and isinstance(output[key], (list, tuple)):
                return list(output[key])
        return [output]
    # Async iterator (e.g. streaming models)
    if hasattr(output, "__aiter__"):
        return [item async for item in output]
    # Sync iterator
    if hasattr(output, "__iter__") and not isinstance(output, (str, bytes)):
        return list(output)
    # Single item (string URL, FileOutput, etc.)
    return [output]


async def _extract_bytes_and_url(item) -> tuple[bytes, str]:
    """Resolve an item to (bytes, url). Handles:
      - FileOutput-like object with .read() / .aread() / .url()
      - Plain URL string
      - dict with 'url' or 'image' key
      - bytes directly
    """
    if isinstance(item, bytes):
        return item, ""

    if isinstance(item, str):
        # Assume it's a URL
        if not (item.startswith("http://") or item.startswith("https://")):
            raise ValueError(f"string item is not a URL: {item[:80]}")
        return await _http_fetch(item), item

    if isinstance(item, dict):
        # Some models return {"url": "...", ...} per image
        url = item.get("url") or item.get("image") or item.get("imageUrl") or ""
        if not url:
            raise ValueError(f"dict item has no url/image key: {list(item.keys())}")
        return await _http_fetch(url), url

    # FileOutput-like: try async read first, then sync read, then fall back to url fetch.
    url = ""
    if hasattr(item, "url"):
        try:
            url_attr = item.url
            url = url_attr() if callable(url_attr) else url_attr
            url = str(url) if url else ""
        except Exception:
            url = ""

    # Prefer async read if available
    if hasattr(item, "aread"):
        result = item.aread()
        if inspect.isawaitable(result):
            data = await result
        else:
            data = result
        return data, url

    if hasattr(item, "read"):
        result = item.read()
        if inspect.isawaitable(result):
            data = await result
        else:
            data = result
        # Some SDK versions return the full bytes from .read(), others return chunks.
        if isinstance(data, bytes):
            return data, url
        # If .read() returned a str path or similar, fall through

    # Last resort: if we got a URL, just fetch it
    if url:
        return await _http_fetch(url), url

    raise ValueError(f"cannot extract bytes from {type(item).__name__}")


async def _http_fetch(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content


# ── Helpers ───────────────────────────────────────────────────────────────────

def _sanitize(name: str) -> str:
    import re
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    name = re.sub(r"[^\w\-. ]", "", name).strip()
    return name or "untitled"
