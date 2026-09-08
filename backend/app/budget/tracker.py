"""
Budget tracker — records token usage per LLM call and checks limits.

Used by the LLM loop in agent.py to:
1. Record usage after each completion call
2. Check if the run has exceeded its budget before making the next call
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.budget.pricing import estimate_cost
from app.db.models.usage import BudgetLimit, TokenUsage
from app.db.session import AsyncSessionLocal

logger = logging.getLogger(__name__)


class BudgetExceeded(Exception):
    """Raised when a run exceeds its budget limit."""
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


async def record_usage(
    run_id: str,
    agent_name: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> TokenUsage:
    """Record a single LLM call's token usage.

    The user is copied from the run rather than threaded through the agent
    loop, which does not know who started it. One indexed primary-key lookup
    per call, in a session this function already opens.
    """
    from app.db.models.run import Run

    cost = estimate_cost(model, input_tokens, output_tokens)
    async with AsyncSessionLocal() as db:
        run = await db.get(Run, run_id)
        user_id = run.user_id if run else None
        usage = TokenUsage(
            run_id=run_id,
            agent_name=agent_name,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=cost,
            user_id=user_id,
        )
        db.add(usage)
        await db.commit()
    return usage


async def check_budget(
    run_id: str, task_id: str, agent_id: str | None, user_id: str | None = None
) -> None:
    """Check all applicable budget limits. Raises BudgetExceeded if any are hit."""
    async with AsyncSessionLocal() as db:
        # Get run totals so far
        run_totals = await _get_run_totals(db, run_id)

        # Resolved here rather than threaded through the agent loop, which has
        # no notion of who started the run.
        if user_id is None:
            from app.db.models.run import Run
            run = await db.get(Run, run_id)
            user_id = run.user_id if run else None

        # Check limits in order: global → agent → task → user, then the
        # subscription plan's own caps.
        limits = await _get_applicable_limits(db, task_id, agent_id, user_id)
        limits.extend(await _plan_limits(db, user_id))

        for limit in limits:
            # Per-run token limit
            if limit.max_tokens_per_run and run_totals["tokens"] >= limit.max_tokens_per_run:
                raise BudgetExceeded(
                    f"Token limit exceeded: {run_totals['tokens']}/{limit.max_tokens_per_run} "
                    f"tokens (scope: {limit.scope_type})"
                )

            # Per-run cost limit
            if limit.max_cost_per_run and run_totals["cost"] >= limit.max_cost_per_run:
                raise BudgetExceeded(
                    f"Run cost limit exceeded: ${run_totals['cost']:.4f}/${limit.max_cost_per_run} "
                    f"(scope: {limit.scope_type})"
                )

            # Daily cost limit (all runs for this scope today)
            if limit.max_cost_per_day:
                daily_cost = await _get_period_cost(
                    db, limit.scope_type, limit.scope_id, days=1
                )
                if daily_cost >= limit.max_cost_per_day:
                    raise BudgetExceeded(
                        f"Daily cost limit exceeded: ${daily_cost:.4f}/${limit.max_cost_per_day} "
                        f"(scope: {limit.scope_type})"
                    )

            # Monthly cost limit
            if limit.max_cost_per_month:
                monthly_cost = await _get_period_cost(
                    db, limit.scope_type, limit.scope_id, days=30
                )
                if monthly_cost >= limit.max_cost_per_month:
                    raise BudgetExceeded(
                        f"Monthly cost limit exceeded: ${monthly_cost:.4f}/${limit.max_cost_per_month} "
                        f"(scope: {limit.scope_type})"
                    )


async def get_run_usage(run_id: str) -> dict:
    """Get aggregated usage for a run."""
    async with AsyncSessionLocal() as db:
        return await _get_run_totals(db, run_id)


async def get_usage_summary(days: int = 30) -> dict:
    """Get aggregated usage across all runs for the last N days."""
    async with AsyncSessionLocal() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await db.execute(
            select(
                func.sum(TokenUsage.input_tokens),
                func.sum(TokenUsage.output_tokens),
                func.sum(TokenUsage.cost_usd),
                func.count(TokenUsage.id),
            ).where(TokenUsage.ts >= cutoff)
        )
        row = result.one()
        return {
            "input_tokens": row[0] or 0,
            "output_tokens": row[1] or 0,
            "total_tokens": (row[0] or 0) + (row[1] or 0),
            "cost_usd": round(row[2] or 0, 4),
            "llm_calls": row[3] or 0,
            "period_days": days,
        }


async def get_usage_by_model(days: int = 30) -> list[dict]:
    """Get usage breakdown by model."""
    async with AsyncSessionLocal() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await db.execute(
            select(
                TokenUsage.model,
                func.sum(TokenUsage.input_tokens),
                func.sum(TokenUsage.output_tokens),
                func.sum(TokenUsage.cost_usd),
                func.count(TokenUsage.id),
            )
            .where(TokenUsage.ts >= cutoff)
            .group_by(TokenUsage.model)
            .order_by(func.sum(TokenUsage.cost_usd).desc())
        )
        return [
            {
                "model": row[0],
                "input_tokens": row[1] or 0,
                "output_tokens": row[2] or 0,
                "cost_usd": round(row[3] or 0, 4),
                "calls": row[4] or 0,
            }
            for row in result.all()
        ]


async def get_usage_by_agent(days: int = 30) -> list[dict]:
    """Get usage breakdown by agent."""
    async with AsyncSessionLocal() as db:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        result = await db.execute(
            select(
                TokenUsage.agent_name,
                func.sum(TokenUsage.input_tokens),
                func.sum(TokenUsage.output_tokens),
                func.sum(TokenUsage.cost_usd),
                func.count(TokenUsage.id),
            )
            .where(TokenUsage.ts >= cutoff)
            .group_by(TokenUsage.agent_name)
            .order_by(func.sum(TokenUsage.cost_usd).desc())
        )
        return [
            {
                "agent": row[0],
                "input_tokens": row[1] or 0,
                "output_tokens": row[2] or 0,
                "cost_usd": round(row[3] or 0, 4),
                "calls": row[4] or 0,
            }
            for row in result.all()
        ]


# ── Internal ──────────────────────────────────────────────────────────────────

async def _get_run_totals(db: AsyncSession, run_id: str) -> dict:
    result = await db.execute(
        select(
            func.sum(TokenUsage.input_tokens),
            func.sum(TokenUsage.output_tokens),
            func.sum(TokenUsage.cost_usd),
        ).where(TokenUsage.run_id == run_id)
    )
    row = result.one()
    return {
        "input_tokens": row[0] or 0,
        "output_tokens": row[1] or 0,
        "tokens": (row[0] or 0) + (row[1] or 0),
        "cost": round(row[2] or 0, 6),
    }


async def _plan_limits(db: AsyncSession, user_id: str | None) -> list[BudgetLimit]:
    """The user's plan caps, as a transient BudgetLimit scoped to them.

    Not persisted: the plan is config, so materialising rows would duplicate it
    into the database and let the two drift. Building the object here keeps one
    source of truth and reuses the existing limit-checking code unchanged.
    """
    if not user_id:
        return []

    from app.plans.service import permissions_for

    perms = await permissions_for(db, user_id)
    if perms.max_cost_per_day is None and perms.max_cost_per_month is None:
        return []

    return [BudgetLimit(
        id=f"plan:{perms.plan_id}",
        scope_type="user",
        scope_id=user_id,
        max_cost_per_day=perms.max_cost_per_day,
        max_cost_per_month=perms.max_cost_per_month,
    )]


async def _get_applicable_limits(
    db: AsyncSession, task_id: str, agent_id: str | None, user_id: str | None = None
) -> list[BudgetLimit]:
    """Get all limits that apply, ordered global → agent → task → user.

    A per-user quota is a scope value, not a new table: budget_limits already
    keys on scope_type/scope_id.
    """
    scope_filters = [BudgetLimit.scope_id == "global"]
    if agent_id:
        scope_filters.append(BudgetLimit.scope_id == agent_id)
    scope_filters.append(BudgetLimit.scope_id == task_id)
    if user_id:
        scope_filters.append(BudgetLimit.scope_id == user_id)

    from sqlalchemy import or_
    result = await db.execute(
        select(BudgetLimit).where(or_(*scope_filters))
    )
    return list(result.scalars().all())


async def _get_period_cost(
    db: AsyncSession, scope_type: str, scope_id: str, days: int
) -> float:
    """Get total cost for a scope over the last N days."""
    from app.db.models.run import Run

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if scope_type == "global":
        result = await db.execute(
            select(func.sum(TokenUsage.cost_usd)).where(TokenUsage.ts >= cutoff)
        )
    elif scope_type == "user":
        # Reads token_usage directly rather than joining through runs: this is
        # evaluated before every LLM call, and a user accumulates far more runs
        # than a task does.
        result = await db.execute(
            select(func.sum(TokenUsage.cost_usd))
            .where(TokenUsage.ts >= cutoff, TokenUsage.user_id == scope_id)
        )
    elif scope_type == "agent":
        result = await db.execute(
            select(func.sum(TokenUsage.cost_usd))
            .join(Run, TokenUsage.run_id == Run.id)
            .where(TokenUsage.ts >= cutoff, Run.agent_id == scope_id)
        )
    else:  # task
        result = await db.execute(
            select(func.sum(TokenUsage.cost_usd))
            .join(Run, TokenUsage.run_id == Run.id)
            .where(TokenUsage.ts >= cutoff, Run.task_id == scope_id)
        )

    return round(result.scalar_one() or 0, 6)
