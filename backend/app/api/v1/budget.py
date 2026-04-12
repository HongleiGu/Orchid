from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.api.schemas import DataResponse
from app.db.models.usage import BudgetLimit
from app.db.session import get_db

router = APIRouter(prefix="/budget", tags=["budget"])


# ── Schemas ───────────────────────────────────────────────────────────────────

class UsageSummary(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float
    llm_calls: int
    period_days: int


class UsageByModel(BaseModel):
    model: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    calls: int


class UsageByAgent(BaseModel):
    agent: str
    input_tokens: int
    output_tokens: int
    cost_usd: float
    calls: int


class BudgetLimitOut(BaseModel):
    id: str
    scope_type: str
    scope_id: str
    max_tokens_per_run: int | None
    max_cost_per_run: float | None
    max_cost_per_day: float | None
    max_cost_per_month: float | None

    model_config = {"from_attributes": True}


class BudgetLimitCreate(BaseModel):
    scope_type: str  # "global" | "agent" | "task"
    scope_id: str    # "global" for global, or entity ID
    max_tokens_per_run: int | None = None
    max_cost_per_run: float | None = None
    max_cost_per_day: float | None = None
    max_cost_per_month: float | None = None


class RunUsage(BaseModel):
    input_tokens: int
    output_tokens: int
    tokens: int
    cost: float


class PricingOut(BaseModel):
    model: str
    input_per_m: float
    output_per_m: float


# ── Usage endpoints ───────────────────────────────────────────────────────────

@router.get("/usage", response_model=DataResponse[UsageSummary])
async def usage_summary(days: int = Query(30, ge=1, le=365)):
    from app.budget.tracker import get_usage_summary
    data = await get_usage_summary(days)
    return DataResponse(data=UsageSummary(**data))


@router.get("/usage/by-model", response_model=DataResponse[list[UsageByModel]])
async def usage_by_model(days: int = Query(30, ge=1, le=365)):
    from app.budget.tracker import get_usage_by_model
    data = await get_usage_by_model(days)
    return DataResponse(data=[UsageByModel(**d) for d in data])


@router.get("/usage/by-agent", response_model=DataResponse[list[UsageByAgent]])
async def usage_by_agent(days: int = Query(30, ge=1, le=365)):
    from app.budget.tracker import get_usage_by_agent
    data = await get_usage_by_agent(days)
    return DataResponse(data=[UsageByAgent(**d) for d in data])


@router.get("/usage/run/{run_id}", response_model=DataResponse[RunUsage])
async def run_usage(run_id: str):
    from app.budget.tracker import get_run_usage
    data = await get_run_usage(run_id)
    return DataResponse(data=RunUsage(**data))


# ── Budget limit endpoints ────────────────────────────────────────────────────

@router.get("/limits", response_model=DataResponse[list[BudgetLimitOut]])
async def list_limits(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(BudgetLimit))
    return DataResponse(data=[BudgetLimitOut.model_validate(l) for l in result.scalars().all()])


@router.post("/limits", response_model=DataResponse[BudgetLimitOut], status_code=201)
async def create_or_update_limit(body: BudgetLimitCreate, db: AsyncSession = Depends(get_db)):
    # Upsert: one limit per scope_type + scope_id
    result = await db.execute(
        select(BudgetLimit).where(
            BudgetLimit.scope_type == body.scope_type,
            BudgetLimit.scope_id == body.scope_id,
        )
    )
    limit = result.scalar_one_or_none()

    if limit:
        limit.max_tokens_per_run = body.max_tokens_per_run
        limit.max_cost_per_run = body.max_cost_per_run
        limit.max_cost_per_day = body.max_cost_per_day
        limit.max_cost_per_month = body.max_cost_per_month
    else:
        limit = BudgetLimit(
            id=str(ULID()),
            scope_type=body.scope_type,
            scope_id=body.scope_id,
            max_tokens_per_run=body.max_tokens_per_run,
            max_cost_per_run=body.max_cost_per_run,
            max_cost_per_day=body.max_cost_per_day,
            max_cost_per_month=body.max_cost_per_month,
        )
        db.add(limit)

    await db.commit()
    await db.refresh(limit)
    return DataResponse(data=BudgetLimitOut.model_validate(limit))


@router.delete("/limits/{limit_id}", status_code=204)
async def delete_limit(limit_id: str, db: AsyncSession = Depends(get_db)):
    limit = await db.get(BudgetLimit, limit_id)
    if not limit:
        raise HTTPException(404, "Limit not found")
    await db.delete(limit)
    await db.commit()


# ── Pricing reference ─────────────────────────────────────────────────────────

@router.get("/pricing", response_model=DataResponse[list[PricingOut]])
async def pricing():
    from app.budget.pricing import get_pricing_table
    table = get_pricing_table()
    return DataResponse(data=[
        PricingOut(model=k, input_per_m=v.input_per_m, output_per_m=v.output_per_m)
        for k, v in sorted(table.items())
    ])
