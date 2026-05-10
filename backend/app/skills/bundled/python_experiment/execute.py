from __future__ import annotations

import ast
import asyncio
import os
import resource
import sys
import tempfile
from pathlib import Path

MAX_CODE_CHARS = 20_000
MAX_OUTPUT_CHARS = 12_000
MAX_TIMEOUT_SECONDS = 30

DENIED_IMPORT_ROOTS = {
    "ctypes",
    "ftplib",
    "glob",
    "http",
    "importlib",
    "multiprocessing",
    "os",
    "pathlib",
    "pickle",
    "pipes",
    "pkgutil",
    "platform",
    "pty",
    "requests",
    "shlex",
    "shutil",
    "signal",
    "socket",
    "ssl",
    "subprocess",
    "sys",
    "tempfile",
    "urllib",
}

DENIED_CALLS = {
    "__import__",
    "breakpoint",
    "compile",
    "eval",
    "exec",
    "exit",
    "getattr",
    "globals",
    "input",
    "locals",
    "open",
    "quit",
    "setattr",
    "vars",
}


async def execute(code: str, timeout_seconds: int = 20) -> str:
    """Run constrained Python code and return stdout/stderr plus status."""
    timeout = max(1, min(int(timeout_seconds or 20), MAX_TIMEOUT_SECONDS))
    cleaned = (code or "").strip()
    if not cleaned:
        return "Error: code must be non-empty."
    if len(cleaned) > MAX_CODE_CHARS:
        return f"Error: code is too long ({len(cleaned)} chars, max {MAX_CODE_CHARS})."

    validation_error = _validate_source(cleaned)
    if validation_error:
        return f"Rejected by python_experiment safety check: {validation_error}"

    with tempfile.TemporaryDirectory(prefix="orchid-exp-") as tmp:
        script = Path(tmp) / "experiment.py"
        script.write_text(cleaned, encoding="utf-8")

        proc = await asyncio.create_subprocess_exec(
            sys.executable,
            "-I",
            "-S",
            str(script),
            cwd=tmp,
            env={"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"},
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            preexec_fn=_limit_child_process,
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


def _validate_source(source: str) -> str | None:
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return f"syntax error at line {exc.lineno}: {exc.msg}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in DENIED_IMPORT_ROOTS:
                    return f"import of {root!r} is not allowed"

        if isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".", 1)[0]
            if root in DENIED_IMPORT_ROOTS:
                return f"import of {root!r} is not allowed"

        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in DENIED_CALLS:
                return f"call to {name!r} is not allowed"

        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return "dunder attribute access is not allowed"

        if isinstance(node, ast.Name) and node.id.startswith("__"):
            return "dunder names are not allowed"

    return None


def _call_name(func: ast.AST) -> str:
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return ""


def _limit_child_process() -> None:
    # Keep experiment probes small even if model-generated code goes sideways.
    resource.setrlimit(resource.RLIMIT_CPU, (35, 35))
    resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1 * 1024 * 1024, 1 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_NOFILE, (16, 16))
    try:
        resource.setrlimit(resource.RLIMIT_NPROC, (4, 4))
    except (ValueError, OSError):
        pass
    os.umask(0o077)
