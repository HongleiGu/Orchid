"""Subscription management CLI (OR-38).

A CLI rather than HTTP routes, for the same reason as the key tool: there is no
admin UI, and write endpoints would be one more surface the run-only profile
has to block. Billing will eventually drive `subscribe` from a payment webhook;
until then an operator runs it by hand.

    docker compose exec backend python -m app.plans.cli plans
    docker compose exec backend python -m app.plans.cli subscribe alice standard --days 30
    docker compose exec backend python -m app.plans.cli show alice
    docker compose exec backend python -m app.plans.cli cancel alice
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.db.models.user import User
from app.plans.registry import load_plans, plan_registry
from app.plans.service import active_plan_id, cancel, permissions_for, subscribe

logger = logging.getLogger(__name__)


def _fmt(value) -> str:
    """None means unrestricted, which is worth saying out loud."""
    if value is None:
        return "unrestricted"
    if isinstance(value, frozenset):
        return ", ".join(sorted(value)) if value else "(none)"
    return str(value)


async def _cli(argv: list[str]) -> int:
    import argparse

    from app.db.session import AsyncSessionLocal, engine

    # See app/auth/keys.py: echo is a flag, not a log level, so it cannot be
    # turned down with logging config.
    engine.echo = False
    load_plans()

    parser = argparse.ArgumentParser(prog="python -m app.plans.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("plans", help="list the plans this deployment defines")

    p_sub = sub.add_parser("subscribe", help="put a user on a plan")
    p_sub.add_argument("identifier", help="the user's identifier, as passed to `keys create`")
    p_sub.add_argument("plan_id")
    p_sub.add_argument("--days", type=int, default=None,
                       help="access ends after this many days (default: open-ended)")

    p_show = sub.add_parser("show", help="a user's plan and effective permissions")
    p_show.add_argument("identifier")

    p_cancel = sub.add_parser("cancel", help="stop renewal; access runs to period_end")
    p_cancel.add_argument("identifier")
    p_cancel.add_argument("--now", action="store_true",
                          help="also end access immediately rather than at period_end")

    args = parser.parse_args(argv)

    if args.command == "plans":
        if not plan_registry.all():
            print("no plans defined — every user runs at the deployment ceiling")
            return 0
        print(f"{'ID':16} {'NAME':24} {'$/DAY':>8}  TEMPLATES")
        for plan in plan_registry.all():
            day = "-" if plan.max_cost_per_day is None else f"{plan.max_cost_per_day:.2f}"
            print(f"{plan.id:16} {plan.name:24} {day:>8}  {', '.join(plan.templates)}")
        return 0

    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.identifier == args.identifier))
        ).scalar_one_or_none()
        if user is None:
            print(f"no such user: {args.identifier!r} (create one with `python -m app.auth.keys create`)")
            return 1

        if args.command == "subscribe":
            if plan_registry.get(args.plan_id) is None:
                # Refused rather than stored: an unknown plan_id resolves to no
                # plan at all, so this would silently do nothing useful.
                print(f"no such plan: {args.plan_id!r}. Defined: {', '.join(plan_registry.ids()) or '(none)'}")
                return 1
            end = (
                datetime.now(timezone.utc) + timedelta(days=args.days)
                if args.days is not None else None
            )
            await subscribe(db, user.id, args.plan_id, period_end=end)
            await db.commit()
            print(f"{user.identifier} -> {args.plan_id}, until {end.isoformat() if end else 'cancelled'}")
            return 0

        if args.command == "cancel":
            count = await cancel(db, user.id)
            if args.now:
                from app.db.models.subscription import Subscription
                rows = (await db.execute(
                    select(Subscription).where(Subscription.user_id == user.id)
                )).scalars().all()
                now = datetime.now(timezone.utc)
                for row in rows:
                    if row.period_end is None or row.period_end > now:
                        row.period_end = now
            await db.commit()
            print(f"cancelled {count} subscription(s)" + (" and ended access now" if args.now else ""))
            return 0

        if args.command == "show":
            plan_id = await active_plan_id(db, user.id)
            perms = await permissions_for(db, user.id)
            print(f"user        {user.identifier} ({user.id})")
            print(f"plan        {plan_id or '(none)'}")
            print(f"templates   {_fmt(perms.templates)}")
            print(f"skills      {_fmt(perms.skills)}")
            print(f"models      {_fmt(perms.models)}")
            print(f"cost/day    {_fmt(perms.max_cost_per_day)}")
            print(f"cost/month  {_fmt(perms.max_cost_per_month)}")
            return 0

    return 1


if __name__ == "__main__":
    import asyncio
    import sys

    logging.basicConfig(level="WARNING")
    sys.exit(asyncio.run(_cli(sys.argv[1:])))
