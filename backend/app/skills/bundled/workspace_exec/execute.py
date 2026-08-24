from __future__ import annotations

import asyncio
import os
import pathlib

from skill_lib.vault import sanitize_name

WORKSPACE_ROOT = "/workspace"
MAX_OUTPUT_CHARS = 16_000
MAX_TIMEOUT = 570


def _workspace_dir(workspace: str) -> pathlib.Path:
    d = pathlib.Path(WORKSPACE_ROOT) / sanitize_name(workspace or "default")
    d.mkdir(parents=True, exist_ok=True)
    return d


async def execute(command: str, workspace: str = "default", timeout_seconds: int = 300) -> str:
    cmd = (command or "").strip()
    if not cmd:
        return "Error: command must be non-empty."
    timeout = max(1, min(int(timeout_seconds or 300), MAX_TIMEOUT))
    wd = _workspace_dir(workspace)

    # Full runner environment (LLM keys, PATH, ...) plus a workspace-local HOME
    # so pip --user installs and caches land inside the workspace.
    env = dict(os.environ)
    env["HOME"] = str(wd)
    env["PYTHONUNBUFFERED"] = "1"

    try:
        proc = await asyncio.create_subprocess_shell(
            cmd, cwd=str(wd), env=env,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out_b, err_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.communicate()
        return (f"status: timeout\nreturncode: -1\ntimeout_seconds: {timeout}\n"
                "The command exceeded the time limit. Run fewer or faster steps "
                "(e.g. lower the number of LLM calls, or split the work across calls).")

    out = out_b.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
    err = err_b.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
    return (
        f"status: {'ok' if proc.returncode == 0 else 'error'}\n"
        f"returncode: {proc.returncode}\nworkspace: {workspace}\n"
        f"stdout:\n{out or '<empty>'}\nstderr:\n{err or '<empty>'}"
    )
