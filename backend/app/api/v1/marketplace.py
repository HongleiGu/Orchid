from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DataResponse
from app.db.session import get_db

router = APIRouter(prefix="/marketplace", tags=["marketplace"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class PackageOut(BaseModel):
    id: str
    npm_name: str
    version: str
    pkg_type: str
    registered_name: str
    description: str
    enabled: bool
    installed_at: datetime

    model_config = {"from_attributes": True}


class InstallRequest(BaseModel):
    package: str  # npm package name, e.g. "@scope/skill-foo" or "skill-foo"


class InstallOut(BaseModel):
    success: bool
    name: str
    npm_name: str
    pkg_type: str
    version: str
    error: str | None = None


class UninstallRequest(BaseModel):
    package: str


class ToggleRequest(BaseModel):
    package: str
    enabled: bool


class RunnerSkillOut(BaseModel):
    name: str
    description: str
    parameters: dict
    pkg_type: str


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/installed", response_model=DataResponse[list[PackageOut]])
async def list_installed(db: AsyncSession = Depends(get_db)):
    from app.marketplace.service import marketplace
    packages = await marketplace.list_installed(db)
    return DataResponse(data=[PackageOut.model_validate(p) for p in packages])


@router.post("/install", response_model=DataResponse[InstallOut])
async def install_package(body: InstallRequest, db: AsyncSession = Depends(get_db)):
    from app.marketplace.service import marketplace
    result = await marketplace.install(body.package, db)
    if not result.success:
        raise HTTPException(400, result.error or "Install failed")
    return DataResponse(data=InstallOut(
        success=result.success,
        name=result.name,
        npm_name=result.npm_name,
        pkg_type=result.pkg_type,
        version=result.version,
    ))


@router.post("/uninstall", response_model=DataResponse[dict])
async def uninstall_package(body: UninstallRequest, db: AsyncSession = Depends(get_db)):
    from app.marketplace.service import marketplace
    result = await marketplace.uninstall(body.package, db)
    if not result.success:
        raise HTTPException(400, result.error or "Uninstall failed")
    return DataResponse(data={"npm_name": result.npm_name, "status": "uninstalled"})


@router.post("/toggle", response_model=DataResponse[dict])
async def toggle_package(body: ToggleRequest, db: AsyncSession = Depends(get_db)):
    from app.marketplace.service import marketplace
    ok = await marketplace.toggle_enabled(body.package, body.enabled, db)
    if not ok:
        raise HTTPException(404, "Package not found")
    return DataResponse(data={"npm_name": body.package, "enabled": body.enabled})


@router.get("/runner/skills", response_model=DataResponse[list[RunnerSkillOut]])
async def runner_skills():
    """List skills currently loaded in the skill-runner sandbox."""
    from app.marketplace.service import marketplace
    skills = await marketplace.get_runner_skills()
    return DataResponse(data=skills)
