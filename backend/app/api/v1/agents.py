from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.api.schemas import DataResponse, PageMeta, PageResponse
from app.db.models.agent import Agent
from app.db.session import get_db

router = APIRouter(prefix="/agents", tags=["agents"])

_PAGE_SIZE = 20


# ── Schemas ───────────────────────────────────────────────────────────────────

class AgentOut(BaseModel):
    id: str
    name: str
    role: str
    system_prompt: str
    model: str | None
    tools: list[str]
    skills: list[str]
    memory_strategy: str
    reasoning: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentCreate(BaseModel):
    name: str
    role: str = "assistant"
    system_prompt: str = ""
    model: str | None = None
    tools: list[str] = []
    skills: list[str] = []
    memory_strategy: str = "none"
    reasoning: bool = False


class AgentUpdate(BaseModel):
    name: str | None = None
    role: str | None = None
    system_prompt: str | None = None
    model: str | None = None
    tools: list[str] | None = None
    skills: list[str] | None = None
    memory_strategy: str | None = None
    reasoning: bool | None = None


def _merge_skill_names(*groups: list[str] | None) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for name in group or []:
            if name not in merged:
                merged.append(name)
    return merged


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("", response_model=PageResponse[AgentOut])
async def list_agents(
    page: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    total = (await db.execute(select(func.count(Agent.id)))).scalar_one()
    rows = (
        await db.execute(
            select(Agent)
            .order_by(Agent.created_at.desc())
            .offset((page - 1) * _PAGE_SIZE)
            .limit(_PAGE_SIZE)
        )
    ).scalars().all()
    return PageResponse(
        data=[AgentOut.model_validate(r) for r in rows],
        meta=PageMeta(page=page, page_size=_PAGE_SIZE, total=total),
    )


@router.get("/{agent_id}", response_model=DataResponse[AgentOut])
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    return DataResponse(data=AgentOut.model_validate(agent))


@router.post("", response_model=DataResponse[AgentOut], status_code=201)
async def create_agent(body: AgentCreate, db: AsyncSession = Depends(get_db)):
    values = body.model_dump()
    values["skills"] = _merge_skill_names(values.get("tools"), values.get("skills"))
    values["tools"] = []
    agent = Agent(id=str(ULID()), **values)
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return DataResponse(data=AgentOut.model_validate(agent))


@router.patch("/{agent_id}", response_model=DataResponse[AgentOut])
async def update_agent(
    agent_id: str, body: AgentUpdate, db: AsyncSession = Depends(get_db)
):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    values = body.model_dump(exclude_none=True)
    if "tools" in values or "skills" in values:
        next_skills = values.get("skills", list(agent.skills or []))
        values["skills"] = _merge_skill_names(values.get("tools"), next_skills)
        values["tools"] = []
    for field, value in values.items():
        setattr(agent, field, value)
    await db.commit()
    await db.refresh(agent)
    return DataResponse(data=AgentOut.model_validate(agent))


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    agent = await db.get(Agent, agent_id)
    if not agent:
        raise HTTPException(404, "Agent not found")
    await db.delete(agent)
    await db.commit()
