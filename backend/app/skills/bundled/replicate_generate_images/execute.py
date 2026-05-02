from __future__ import annotations

import inspect
import json
import logging
import os
from datetime import datetime, timezone

import httpx

from skill_lib.vault import sanitize_name, vault_dir

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "bytedance/seedream-5-lite"


async def execute(
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
    token = os.environ.get("REPLICATE_API_TOKEN", "")
    if not token:
        return "Error: REPLICATE_API_TOKEN not set"

    try:
        import replicate
    except ImportError:
        return "Error: `replicate` package not installed."

    os.environ["REPLICATE_API_TOKEN"] = token

    payload = {
        "prompt": prompt,
        "image_input": [],
        "max_images": max_images,
        "aspect_ratio": aspect_ratio,
        "size": size,
        "output_format": output_format,
        "sequential_image_generation": sequential_image_generation,
    }

    try:
        output = await replicate.async_run(model, input=payload)
    except Exception as exc:
        return f"Replicate generation failed: {exc}"

    try:
        items = await _collect_items(output)
    except Exception as exc:
        return f"Replicate output collection failed ({type(output).__name__}): {exc}"

    if not items:
        return f"Replicate returned no images. Raw output type: {type(output).__name__}."

    project_safe = sanitize_name(vault_project)
    assets_dir = vault_dir() / project_safe / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    if not filename_prefix:
        filename_prefix = datetime.now(timezone.utc).strftime("story-%Y%m%d-%H%M%S")
    filename_prefix = sanitize_name(filename_prefix)

    saved: list[dict] = []
    errors: list[str] = []
    for i, item in enumerate(items):
        try:
            data, url = await _extract_bytes_and_url(item)
        except Exception as exc:
            errors.append(f"item {i}: {type(item).__name__} → {type(exc).__name__}: {exc}")
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


async def _collect_items(output) -> list:
    if output is None:
        return []
    if isinstance(output, (list, tuple)):
        return list(output)
    if isinstance(output, dict):
        for key in ("images", "output", "results", "urls"):
            if key in output and isinstance(output[key], (list, tuple)):
                return list(output[key])
        return [output]
    if hasattr(output, "__aiter__"):
        return [item async for item in output]
    if hasattr(output, "__iter__") and not isinstance(output, (str, bytes)):
        return list(output)
    return [output]


async def _extract_bytes_and_url(item) -> tuple[bytes, str]:
    if isinstance(item, bytes):
        return item, ""
    if isinstance(item, str):
        if not (item.startswith("http://") or item.startswith("https://")):
            raise ValueError(f"string item is not a URL: {item[:80]}")
        return await _http_fetch(item), item
    if isinstance(item, dict):
        url = item.get("url") or item.get("image") or item.get("imageUrl") or ""
        if not url:
            raise ValueError(f"dict item has no url/image key: {list(item.keys())}")
        return await _http_fetch(url), url

    url = ""
    if hasattr(item, "url"):
        try:
            url_attr = item.url
            url = url_attr() if callable(url_attr) else url_attr
            url = str(url) if url else ""
        except Exception:
            url = ""

    if hasattr(item, "aread"):
        result = item.aread()
        data = await result if inspect.isawaitable(result) else result
        return data, url
    if hasattr(item, "read"):
        result = item.read()
        data = await result if inspect.isawaitable(result) else result
        if isinstance(data, bytes):
            return data, url

    if url:
        return await _http_fetch(url), url
    raise ValueError(f"cannot extract bytes from {type(item).__name__}")


async def _http_fetch(url: str) -> bytes:
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.content
