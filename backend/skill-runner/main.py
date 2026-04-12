"""
Skill-runner: sandboxed micro-service for executing marketplace skills/tools.

Endpoints:
  POST /execute           — run a skill by name with kwargs
  POST /install-deps      — pip install from a requirements.txt path
  GET  /list              — list all loaded skills
  GET  /health            — liveness check
  POST /reload            — rescan packages dir and reload all
  POST /reload/{name}     — reload a single package
  POST /unload/{name}     — unload a single package
"""
from __future__ import annotations

import asyncio
import logging
import subprocess
import sys
import traceback
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from loader import LoadedSkill, get_loaded, get_skill, load_single, scan_and_load, unload, PACKAGES_DIR

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EXECUTE_TIMEOUT = 30  # seconds


@asynccontextmanager
async def lifespan(app: FastAPI):
    scan_and_load()
    yield


app = FastAPI(title="Orchid Skill Runner", version="0.1.0", lifespan=lifespan)


# ── Schemas ───────────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    skill_name: str
    kwargs: dict = {}


class ExecuteResponse(BaseModel):
    result: str
    error: str | None = None


class InstallDepsRequest(BaseModel):
    requirements_path: str  # path relative to /packages/node_modules/


class SkillInfo(BaseModel):
    name: str
    description: str
    parameters: dict
    pkg_type: str
    package_dir: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    return {"status": "ok", "loaded": len(get_loaded())}


@app.get("/list", response_model=list[SkillInfo])
async def list_skills():
    return [
        SkillInfo(
            name=s.name,
            description=s.description,
            parameters=s.parameters,
            pkg_type=s.pkg_type,
            package_dir=str(s.package_dir),
        )
        for s in get_loaded().values()
    ]


@app.post("/execute", response_model=ExecuteResponse)
async def execute(req: ExecuteRequest):
    skill = get_skill(req.skill_name)
    if not skill:
        raise HTTPException(404, f"Skill {req.skill_name!r} not loaded")

    try:
        result = await asyncio.wait_for(
            _run_skill(skill, req.kwargs),
            timeout=EXECUTE_TIMEOUT,
        )
        return ExecuteResponse(result=result)
    except asyncio.TimeoutError:
        return ExecuteResponse(
            result="",
            error=f"Skill {req.skill_name!r} timed out after {EXECUTE_TIMEOUT}s",
        )
    except Exception as exc:
        tb = traceback.format_exc()
        logger.error("Skill %r execution error:\n%s", req.skill_name, tb)
        return ExecuteResponse(result="", error=str(exc))


@app.post("/install-deps")
async def install_deps(req: InstallDepsRequest):
    """Install Python dependencies from a package's requirements.txt."""
    req_path = PACKAGES_DIR / req.requirements_path
    if not req_path.exists():
        raise HTTPException(404, f"requirements.txt not found at {req.requirements_path}")

    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "--no-cache-dir", "-r", str(req_path)],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode != 0:
            return {"status": "error", "output": result.stderr}
        return {"status": "ok", "output": result.stdout}
    except subprocess.TimeoutExpired:
        return {"status": "error", "output": "pip install timed out"}


@app.post("/reload")
async def reload_all():
    """Rescan packages directory and reload all skills."""
    loaded = scan_and_load()
    return {"status": "ok", "loaded": len(loaded)}


@app.post("/reload/{name}")
async def reload_single(name: str):
    """Reload a single package by scanning for it in packages dir."""
    # Find the package dir
    for pkg_dir in _find_package_dir(name):
        skill = load_single(pkg_dir)
        if skill:
            return {"status": "ok", "name": skill.name, "type": skill.pkg_type}
    raise HTTPException(404, f"Package for skill {name!r} not found in packages dir")


@app.post("/unload/{name}")
async def unload_skill(name: str):
    if unload(name):
        return {"status": "ok"}
    raise HTTPException(404, f"Skill {name!r} not loaded")


# ── Internal ──────────────────────────────────────────────────────────────────

async def _run_skill(skill: LoadedSkill, kwargs: dict) -> str:
    """Execute a skill, handling both sync and async execute functions."""
    result = skill.execute_fn(**kwargs)
    if asyncio.iscoroutine(result) or asyncio.isfuture(result):
        result = await result
    return str(result)


def _find_package_dir(name: str):
    """Search packages dir for a package whose loaded name matches."""
    if not PACKAGES_DIR.exists():
        return
    for entry in PACKAGES_DIR.iterdir():
        if entry.is_dir() and entry.name.startswith("@"):
            for sub in entry.iterdir():
                if sub.is_dir():
                    yield sub
        elif entry.is_dir():
            yield entry
