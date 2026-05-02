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

import httpx

from skill_lib.vault import sanitize_name, vault_dir

logger = logging.getLogger(__name__)

_BASE = "https://openapi.liblibai.cloud"
_DEFAULT_SUBMIT_PATH = "/api/generate/webui/text2img"
_STATUS_PATH = "/api/generate/webui/status"
_DEFAULT_TEMPLATE_UUID = "e10adc3949ba59abbe56e057f20f883e"
_POLL_INTERVAL = 3.0
_POLL_TIMEOUT = 180


async def execute(
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
    access_key = os.environ.get("LIBLIB_ACCESS_KEY", "")
    secret_key = os.environ.get("LIBLIB_SECRET_KEY", "")
    if not access_key or not secret_key:
        return "Error: LIBLIB_ACCESS_KEY / LIBLIB_SECRET_KEY not set"

    generate_params: dict = {
        "checkPointId": checkpoint_id,
        "prompt": prompt,
        "negativePrompt": negative_prompt,
        "sampler": 15,
        "steps": steps,
        "cfgScale": cfg_scale,
        "width": width,
        "height": height,
        "imgCount": 1,
        "randnSource": 0,
        "seed": seed,
        "restoreFaces": 0,
        "additionalNetwork": _parse_loras(lora_ids),
    }

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
        generate_uuid = await _submit(access_key, secret_key, body, path)
        image_urls = await _poll_until_done(access_key, secret_key, generate_uuid)
        if not image_urls:
            return f"LibLib returned no images for generateUuid={generate_uuid}"
        saved = await _download_to_vault(image_urls[0], vault_project, filename, seed)
        return json.dumps({
            "type": "image",
            "vault_path": saved,
            "remote_url": image_urls[0],
            "prompt": prompt,
            "seed": seed,
            "width": width,
            "height": height,
            "generate_uuid": generate_uuid,
        })
    except Exception as exc:
        return f"LibLib generate failed: {exc}"


def _sign(secret: str, uri: str) -> tuple[str, str, str]:
    ts = str(int(time.time() * 1000))
    nonce = _secrets.token_urlsafe(8)
    to_sign = f"{uri}&{ts}&{nonce}"
    mac = hmac.new(secret.encode(), to_sign.encode(), hashlib.sha1).digest()
    sig = base64.urlsafe_b64encode(mac).decode().rstrip("=")
    return sig, ts, nonce


def _auth_params(access_key: str, secret_key: str, uri: str) -> dict:
    sig, ts, nonce = _sign(secret_key, uri)
    return {"AccessKey": access_key, "Signature": sig, "Timestamp": ts, "SignatureNonce": nonce}


async def _submit(access_key: str, secret_key: str, body: dict, path: str) -> str:
    params = _auth_params(access_key, secret_key, path)
    async with httpx.AsyncClient(timeout=20) as client:
        resp = await client.post(f"{_BASE}{path}", params=params, json=body)
        data = resp.json()
    if resp.status_code >= 400 or data.get("code") not in (0, "0"):
        raise RuntimeError(
            f"LibLib submit error at {path}: HTTP {resp.status_code} {data}. "
            "Common causes: wrong templateUuid, wrong endpoint, body shape mismatch."
        )
    generate_uuid = (data.get("data") or {}).get("generateUuid")
    if not generate_uuid:
        raise RuntimeError(f"LibLib submit returned no generateUuid: {data}")
    return generate_uuid


async def _poll_until_done(access_key: str, secret_key: str, generate_uuid: str) -> list[str]:
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
        if status == 5:
            images = payload.get("images") or []
            return [img.get("imageUrl") for img in images if img.get("imageUrl")]
        if status in (6, 7):
            msg = payload.get("generateMsg") or "generation failed"
            raise RuntimeError(f"LibLib generation failed: {msg}")
    raise TimeoutError(f"LibLib generation timed out after {_POLL_TIMEOUT}s (last status: {last_status})")


async def _download_to_vault(url: str, project: str, filename: str, seed: int) -> str:
    project_safe = sanitize_name(project)
    if not filename:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        seed_tag = f"s{seed}" if seed != -1 else "rand"
        filename = f"scene-{stamp}-{seed_tag}"
    filename = sanitize_name(filename)
    if not filename.endswith(".png"):
        filename += ".png"

    assets_dir = vault_dir() / project_safe / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)
    target = assets_dir / filename

    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        target.write_bytes(resp.content)
    return f"{project_safe}/assets/{filename}"


def _parse_loras(spec: str) -> list[dict]:
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
