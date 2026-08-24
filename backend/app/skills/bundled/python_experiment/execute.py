from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

try:
    import resource as _resource
    _HAS_RESOURCE = True
except ImportError:
    _HAS_RESOURCE = False  # Windows — subprocess isolation + timeout still applies

MAX_CODE_CHARS = 20_000
MAX_OUTPUT_CHARS = 12_000
MAX_TIMEOUT_SECONDS = 120

# LLM-provider credentials passed through to the experiment subprocess so an
# experiment can make real inference calls (via stdlib urllib) when the
# hypothesis genuinely requires a live model. Only these keys are forwarded —
# the rest of the runner env (Jira, Gmail, GitHub, etc.) stays out of the
# experiment sandbox.
_LLM_ENV_PASSTHROUGH = (
    "OPENROUTER_API_KEY", "OPENROUTER_API_BASE",
    "OPENAI_API_KEY", "OPENAI_API_BASE",
    "LLM_DEFAULT_MODEL",
)


def _child_env() -> dict[str, str]:
    env = {"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"}
    for key in _LLM_ENV_PASSTHROUGH:
        val = os.environ.get(key)
        if val:
            env[key] = val
    return env


async def execute(code: str, timeout_seconds: int = 20) -> str:
    """Run Python code in the skill-runner container and return stdout/stderr."""
    timeout = max(1, min(int(timeout_seconds or 20), MAX_TIMEOUT_SECONDS))
    cleaned = (code or "").strip()
    if not cleaned:
        return "Error: code must be non-empty."
    if len(cleaned) > MAX_CODE_CHARS:
        return f"Error: code is too long ({len(cleaned)} chars, max {MAX_CODE_CHARS})."

    with tempfile.TemporaryDirectory(prefix="orchid-exp-") as tmp:
        script = Path(tmp) / "experiment.py"
        script.write_text(cleaned, encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-S",
            str(script),
            cwd=tmp,
            env=_child_env(),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_limit_child_process if _HAS_RESOURCE else None,
        )
        try:
            stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            return f"status: timeout\nreturncode: -1\ntimeout_seconds: {timeout}"

    stdout = stdout_b.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
    stderr = stderr_b.decode("utf-8", errors="replace")[:MAX_OUTPUT_CHARS]
    return (
        f"status: {'ok' if proc.returncode == 0 else 'error'}\n"
        f"returncode: {proc.returncode}\n"
        f"stdout:\n{stdout or '<empty>'}\n"
        f"stderr:\n{stderr or '<empty>'}"
    )


def _limit_child_process() -> None:
    # Belt-and-suspenders OS limits on top of the subprocess sandbox.
    # Only called on Unix where the resource module is available.
    # CPU-time headroom is generous because live LLM calls are I/O-bound (they
    # wait on the network, consuming little CPU) but a run may span ~2 minutes.
    _resource.setrlimit(_resource.RLIMIT_CPU, (110, 110))
    _resource.setrlimit(_resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    _resource.setrlimit(_resource.RLIMIT_FSIZE, (1 * 1024 * 1024, 1 * 1024 * 1024))
    # Enough descriptors for TLS sockets + CA cert bundle when calling an LLM API.
    _resource.setrlimit(_resource.RLIMIT_NOFILE, (64, 64))
    try:
        _resource.setrlimit(_resource.RLIMIT_NPROC, (4, 4))
    except (ValueError, OSError):
        pass
    os.umask(0o077)
