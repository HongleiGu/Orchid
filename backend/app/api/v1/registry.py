"""Lists all registered skills (bundled + marketplace)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.schemas import DataResponse
from app.skills.registry import skill_registry

router = APIRouter(prefix="/registry", tags=["registry"])


class RegisteredItem(BaseModel):
    name: str
    description: str
    type: str = "skill"
    source: str       # "bundled" | "marketplace"
    parameters: dict


@router.get("/all", response_model=DataResponse[list[RegisteredItem]])
async def list_all():
    items: list[RegisteredItem] = [
        RegisteredItem(
            name=s.name,
            description=s.description,
            type="skill",
            source="bundled" if s.name.startswith("@orchid/") else "marketplace",
            parameters=s.parameters,
        )
        for s in skill_registry.all()
    ]
    return DataResponse(data=items)
