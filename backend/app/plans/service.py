"""Resolving a user's effective permissions (OR-38).

Bridges layer 3 (membership, database) to layers 1-2 (ceiling and plans, both
config). Callers ask "what may this user do" and get one answer with the
narrowing already applied.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.db.models.subscription import Subscription
from app.plans.registry import EffectivePermissions, resolve_permissions

logger = logging.getLogger(__name__)


async def active_plan_id(db: AsyncSession, user_id: str | None) -> str | None:
    """The user's current plan, or None.

    A cancelled subscription still counts until period_end: someone who has
    paid through the month keeps what they paid for.
    """
    if not user_id:
        return None

    now = datetime.now(timezone.utc)
    row = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id)
        .where(Subscription.period_start <= now)
        .where(
            (Subscription.period_end.is_(None)) | (Subscription.period_end > now)
        )
        .order_by(Subscription.created_at.desc())
        .limit(1)
    )
    sub = row.scalar_one_or_none()
    return sub.plan_id if sub else None


async def permissions_for(db: AsyncSession, user_id: str | None) -> EffectivePermissions:
    """Effective permissions for a user: ceiling, narrowed by their plan.

    An unsubscribed user gets the ceiling. That keeps a deployment working when
    plans are introduced, and is the right answer for the single-customer case
    where tiers do not exist. PLAN_REQUIRED=true flips it so an unsubscribed
    user gets nothing instead — the setting a paid multi-tenant service wants.
    """
    from app.config import get_settings

    plan_id = await active_plan_id(db, user_id)

    if plan_id is None and get_settings().plan_required:
        # Deny everything by handing back empty sets rather than None, which
        # means "unrestricted".
        return EffectivePermissions(
            plan_id=None,
            templates=frozenset(),
            skills=frozenset(),
            models=frozenset(),
            max_cost_per_day=0.0,
            max_cost_per_month=0.0,
            max_runs_per_day=0,
        )

    return resolve_permissions(plan_id)


async def subscribe(
    db: AsyncSession,
    user_id: str,
    plan_id: str,
    period_end: datetime | None = None,
) -> Subscription:
    """Put a user on a plan. The most recent active row wins, so this both
    creates and upgrades."""
    sub = Subscription(
        id=str(ULID()), user_id=user_id, plan_id=plan_id, period_end=period_end
    )
    db.add(sub)
    await db.flush()
    return sub


async def cancel(db: AsyncSession, user_id: str) -> int:
    """Mark every subscription cancelled. Returns how many were affected.

    period_end is left alone: cancelling ends renewal, not access already paid
    for. Set period_end explicitly to cut access off immediately.
    """
    rows = (
        await db.execute(
            select(Subscription)
            .where(Subscription.user_id == user_id, Subscription.status == "active")
        )
    ).scalars().all()
    for sub in rows:
        sub.status = "cancelled"
    await db.flush()
    return len(rows)
