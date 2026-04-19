"""
LibLibAI image generation — async submit+poll pattern.

LibLib's API flow:
  1. POST submit → returns generateUuid
  2. GET status every few seconds → status=5 means success
  3. Response contains image URLs hosted on LibLib's CDN (temporary)
  4. We download them to vault so the link doesn't expire

Auth: HMAC-SHA1 signature in query params on every call.
  to_sign = f"{uri}&{timestamp_ms}&{nonce}"
  signature = base64url(hmac_sha1(secret, to_sign)).rstrip("=")

Credentials: LIBLIB_ACCESS_KEY / LIBLIB_SECRET_KEY in .env.

Template UUIDs (selected by model family):
  SDXL Ultra: e10adc3949ba59abbe56e057f20f883e
  Flux text2img: 6f7c4652458d4802969f8d089cf5b91f  (default used below)
If the user's model expects a different workflow template, override via
`template_uuid` param.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import logging
import os
import secrets as _secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.tools.base import BaseTool

logger = logging.getLogger(__name__)

_BASE = "https://openapi.liblibai.cloud"
# Per LibLib docs §4.1.3: POST /api/generate/webui/text2img
_DEFAULT_SUBMIT_PATH = "/api/generate/webui/text2img"
_STATUS_PATH = "/api/generate/webui/status"
# Default template UUID from LibLib docs example — generic webui text2img workflow.
# Accepts any checkPointId (SD1.5, SDXL, Flux-derived customs, etc.).
_DEFAULT_TEMPLATE_UUID = "e10adc3949ba59abbe56e057f20f883e"

_POLL_INTERVAL = 3.0          # seconds between status checks
_POLL_TIMEOUT = 180           # give up after 3 minutes

VAULT_DIR = Path(os.environ.get("VAULT_DIR", "/app/vault"))


class LiblibGenerateImageTool(BaseTool):
    name = "@orchid/liblib_generate_image"
    description = (
        "Image generation with LoRA support (Flux / SDXL via LibLibAI). Use only "
        "when you need a specific LoRA style or fine model control; for plain "
        "image generation prefer generate_image (simpler, faster)."
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "Positive prompt. Detailed visual description.",
            },
            "negative_prompt": {
                "type": "string",
                "default": "",
                "description": "Things to avoid in the image.",
            },
            "checkpoint_id": {
                "type": "string",
                "description": "LibLib model version UUID (the `versionUuid` in the model URL).",
            },
            "lora_ids": {
                "type": "string",
                "default": "",
                "description": "Comma-separated LoRA version UUIDs. Use `uuid:weight` to set weight (default 0.8).",
            },
            "width": {"type": "integer", "default": 1024},
            "height": {"type": "integer", "default": 1024},
            "steps": {"type": "integer", "default": 20},
            "cfg_scale": {"type": "number", "default": 3.5},
            "seed": {"type": "integer", "default": -1, "description": "-1 = random."},
            "template_uuid": {
                "type": "string",
                "default": "",
                "description": "Override the workflow template UUID. Empty = LibLib's default webui text2img template.",
            },
            "submit_path": {
                "type": "string",
                "default": "",
                "description": "Override submit endpoint path. Empty = /api/generate/webui/text2img.",
            },
            "extra_params_json": {
                "type": "string",
                "default": "",
                "description": "Optional JSON object merged into `generateParams` (override any default field). Use this when the template expects a different shape.",
            },
            "vault_project": {
                "type": "string",
                "default": "bedtime-stories",
                "description": "Vault subfolder to save the image in.",
            },
            "filename": {
                "type": "string",
                "default": "",
                "description": "File stem without extension. Auto-generated from timestamp+seq if empty.",
            },
        },
        "required": ["prompt", "checkpoint_id"],
    }

    async def call(
        self,
        prompt: str,
        checkpoint_id: str,
        negative_prompt: str = "",
        lora_ids: str = "",
        width: int = 1024,
        height: int = 1024,
        steps: int = 20,
        cfg_scale: float = 3.5,
        seed: int = -1,
        template_uuid: str = "",
        submit_path: str = "",
        extra_params_json: str = "",
        vault_project: str = "bedtime-stories",
        filename: str = "",
    ) -> str:
        from app.config import get_settings
        s = get_settings()
        if not s.liblib_access_key or not s.liblib_secret_key:
            return "Error: LIBLIB_ACCESS_KEY / LIBLIB_SECRET_KEY not set in .env"

        # Body fields follow LibLib docs §4.1.3.1 exactly.
        generate_params: dict = {
            "checkPointId": checkpoint_id,
            "prompt": prompt,
            "negativePrompt": negative_prompt,
            "sampler": 15,          # Euler a
            "steps": steps,
            "cfgScale": cfg_scale,
            "width": width,
            "height": height,
            "imgCount": 1,
            "randnSource": 0,        # 0=CPU, 1=GPU
            "seed": seed,
            "restoreFaces": 0,
            "additionalNetwork": _parse_loras(lora_ids),
        }

        # Allow the caller to override any field (e.g. aspectRatio vs width/height,
        # template-specific keys we haven't hardcoded).
        if extra_params_json:
            try:
                overrides = json.loads(extra_params_json)
                if not isinstance(overrides, dict):
                    return f"extra_params_json must be a JSON object, got {type(overrides).__name__}"
                generate_params.update(overrides)
            except json.JSONDecodeError as exc:
                return f"extra_params_json is not valid JSON: {exc}"

        body = {
            "templateUuid": template_uuid or _DEFAULT_TEMPLATE_UUID,
            "generateParams": generate_params,
        }
        path = submit_path or _DEFAULT_SUBMIT_PATH

        try:
            generate_uuid = await _submit(
                s.liblib_access_key, s.liblib_secret_key, body, path
            )
            image_urls = await _poll_until_done(
                s.liblib_access_key, s.liblib_secret_key, generate_uuid
            )
            if not image_urls:
                return f"LibLib returned no images for generateUuid={generate_uuid}"

            # Download + save first image to vault (single-image tool)
            saved_path = await _download_to_vault(
                image_urls[0], vault_project, filename, seed
            )

            return json.dumps({
                "type": "image",
                "vault_path": saved_path,
                "remote_url": image_urls[0],
                "prompt": prompt,
                "seed": seed,
                "width": width,
                "height": height,
                "generate_uuid": generate_uuid,
            })
        except Exception as exc:
            logger.exception("LibLib generate failed")
            return f"LibLib generate failed: {exc}"


# ── Auth ──────────────────────────────────────────────────────────────────────

def _sign(secret: str, uri: str) -> tuple[str, str, str]:
    """Returns (signature, timestamp_ms_str, nonce)."""
    ts = str(int(time.time() * 1000))
    nonce = _secrets.token_urlsafe(8)
    to_sign = f"{uri}&{ts}&{nonce}"
    mac = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha1).digest()
    sig = base64.urlsafe_b64encode(mac).decode().rstrip("=")
    return sig, ts, nonce


def _auth_params(access_key: str, secret_key: str, uri: str) -> dict:
    sig, ts, nonce = _sign(secret_key, uri)
    return {
        "AccessKey": access_key,
        "Signature": sig,
        "Timestamp": ts,
        "SignatureNonce": nonce,
    }


# ── Submit / poll / download ──────────────────────────────────────────────────

async def _submit(access_key: str, secret_key: str, body: dict, path: str) -> str:
    params = _auth_params(access_key, secret_key, path)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(f"{_BASE}{path}", params=params, json=body)
        data = resp.json()
    if resp.status_code >= 400 or data.get("code") not in (0, "0"):
        # Log the request body at DEBUG so we can diagnose template mismatches
        # without leaking prompts into user-facing error strings.
        logger.debug("LibLib submit rejected body=%s", body)
        raise RuntimeError(
            f"LibLib submit error at {path}: HTTP {resp.status_code} {data}. "
            f"Common causes: wrong templateUuid, wrong endpoint for the model "
            f"family, or body shape mismatch. Try extra_params_json / submit_path / template_uuid."
        )
    generate_uuid = (data.get("data") or {}).get("generateUuid")
    if not generate_uuid:
        raise RuntimeError(f"LibLib submit returned no generateUuid: {data}")
    return generate_uuid


async def _poll_until_done(access_key: str, secret_key: str, generate_uuid: str) -> list[str]:
    """Returns list of image URLs when complete. Raises on failure/timeout."""
    deadline = time.time() + _POLL_TIMEOUT
    last_status = None
    while time.time() < deadline:
        await asyncio.sleep(_POLL_INTERVAL)
        params = _auth_params(access_key, secret_key, _STATUS_PATH)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{_BASE}{_STATUS_PATH}",
                params=params,
                json={"generateUuid": generate_uuid},
            )
            data = resp.json()

        if resp.status_code >= 400 or data.get("code") not in (0, "0"):
            raise RuntimeError(f"LibLib status error: HTTP {resp.status_code} {data}")

        payload = data.get("data") or {}
        status = payload.get("generateStatus")
        last_status = status

        # LibLib statuses: 1=queued, 2=processing, 3=processing, 5=success, 6/7=failed
        if status == 5:
            images = payload.get("images") or []
            return [img.get("imageUrl") for img in images if img.get("imageUrl")]
        if status in (6, 7):
            msg = payload.get("generateMsg") or "generation failed"
            raise RuntimeError(f"LibLib generation failed: {msg}")

    raise TimeoutError(
        f"LibLib generation timed out after {_POLL_TIMEOUT}s (last status: {last_status})"
    )


async def _download_to_vault(
    url: str, project: str, filename: str, seed: int,
) -> str:
    """Download image bytes to vault/<project>/assets/<filename>.png.
    Returns the relative vault path (project/assets/filename.png)."""
    project_safe = _sanitize(project)
    if not filename:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        seed_tag = f"s{seed}" if seed != -1 else "rand"
        filename = f"scene-{stamp}-{seed_tag}"
    filename = _sanitize(filename)
    if not filename.endswith(".png"):
        filename += ".png"

    assets_dir = VAULT_DIR / project_safe / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / filename

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        target.write_bytes(resp.content)

    return f"{project_safe}/assets/{filename}"


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_loras(spec: str) -> list[dict]:
    """Parse 'uuid1,uuid2:0.6,uuid3' into LibLib's additionalNetwork shape."""
    out: list[dict] = []
    for part in (spec or "").split(","):
        part = part.strip()
        if not part:
            continue
        if ":" in part:
            uuid, weight_str = part.split(":", 1)
            try:
                weight = float(weight_str)
            except ValueError:
                weight = 0.8
        else:
            uuid, weight = part, 0.8
        out.append({"modelId": uuid.strip(), "weight": weight})
    return out


def _sanitize(name: str) -> str:
    import re
    name = name.replace("..", "").replace("/", "").replace("\\", "")
    name = re.sub(r"[^\w\-. ]", "", name).strip()
    return name or "untitled"
