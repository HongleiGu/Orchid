"""Lists all registered tools and skills (builtin + bundled + marketplace)."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from app.api.schemas import DataResponse

router = APIRouter(prefix="/registry", tags=["registry"])


class RegisteredItem(BaseModel):
    name: str
    description: str
    type: str         # "tool" | "skill"
    source: str       # "builtin" | "bundled" | "marketplace"
    parameters: dict


@router.get("/all", response_model=DataResponse[list[RegisteredItem]])
async def list_all():
    from app.tools.registry import tool_registry
    from app.skills.registry import skill_registry

    items: list[RegisteredItem] = []

    for t in tool_registry.all():
        items.append(RegisteredItem(
            name=t.name,
            description=t.description,
            type="tool",
            source=_classify(t.name),
            parameters=t.parameters,
        ))

    for s in skill_registry.all():
        items.append(RegisteredItem(
            name=s.name,
            description=s.description,
            type="skill",
            source=_classify(s.name),
            parameters=s.parameters,
        ))

    return DataResponse(data=items)


def _classify(name: str) -> str:
    if not name.startswith("@orchid/"):
        return "marketplace"
    # Bundled skills have "skill-" in the name (e.g. @orchid/skill-weather)
    # Builtins don't (e.g. @orchid/web_search, @orchid/gmail_send)
    short = name.removeprefix("@orchid/")
    if short.startswith("skill-"):
        return "bundled"
    return "builtin"
