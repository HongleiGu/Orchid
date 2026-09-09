"""Seed a test user, API key and subscription — the reproducible way to get a
box into a testable state (see TESTING.md).

    docker compose exec backend python scripts/seed_test_user.py
    docker compose exec backend python scripts/seed_test_user.py --identifier bob --plan standard

This exists because database *state* cannot travel in git the way schema does.
Migrations already ride along with a pull and run from the entrypoint; the rows
a tester needs do not, and committing Postgres's data directory to solve that
would put binary files, key hashes and a torn snapshot of a running cluster
into the repository. A script is text, reviewable, and re-runnable anywhere.

Idempotent: re-running reuses the existing user and subscription. A new key is
only issued when there is no live one, or when --new-key is passed, because the
plaintext cannot be recovered after issuance.

It deliberately does NOT accept the attestation on the user's behalf. An
operator recording an acceptance that did not happen is worse than no record —
the evidentiary value is that the user did it themselves (OR-40). The command
to run as the user is printed at the end.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Runnable as `python scripts/seed_test_user.py` from /app, where the app
# package is a sibling of this directory rather than on sys.path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.attestations.registry import attestation_registry, load_attestations  # noqa: E402
from app.auth.keys import get_or_create_user, issue_key  # noqa: E402
from app.db.models.user import ApiKey  # noqa: E402
from app.plans.registry import load_plans, plan_registry  # noqa: E402
from app.plans.service import active_plan_id, subscribe  # noqa: E402


async def main(args: argparse.Namespace) -> int:
    from app.db.session import AsyncSessionLocal, engine

    # echo is a flag on SQLAlchemy's InstanceLogger, not a log level, so it
    # cannot be turned down with logging config — and it would bury the one
    # line that matters here.
    engine.echo = False

    load_plans()
    load_attestations()

    if plan_registry.get(args.plan) is None:
        print(f"no such plan: {args.plan!r}. Defined: {', '.join(plan_registry.ids()) or '(none)'}")
        return 1

    async with AsyncSessionLocal() as db:
        user = await get_or_create_user(db, args.identifier)
        await db.flush()

        live = (
            await db.execute(
                select(ApiKey)
                .where(ApiKey.user_id == user.id, ApiKey.revoked_at.is_(None))
                .order_by(ApiKey.created_at.desc())
            )
        ).scalars().first()

        plaintext = None
        if live is None or args.new_key:
            _, plaintext = await issue_key(db, user, args.name)

        current = await active_plan_id(db, user.id)
        if current != args.plan:
            end = (
                datetime.now(timezone.utc) + timedelta(days=args.days)
                if args.days else None
            )
            await subscribe(db, user.id, args.plan, period_end=end)

        await db.commit()

        print(f"user        {user.identifier} ({user.id})")
        print(f"plan        {args.plan}" + ("" if current != args.plan else "  (already subscribed)"))

        if plaintext:
            print(f"key         {plaintext}")
            print()
            print("Add these to .env — only the hash is stored, so the key cannot be shown again:")
            print()
            print(f"TEST_BASE_URL={args.base_url}")
            print(f"TEST_API_KEY={plaintext}")
        else:
            print(f"key         reusing {live.prefix}… ({live.id})")
            print("            pass --new-key to issue another; the old plaintext is unrecoverable")

        gated = [a.id for a in attestation_registry.all()]
        if gated:
            print()
            print("Templates requiring an attestation stay locked until the USER accepts.")
            print("Not done here on purpose: a record of an acceptance that did not happen")
            print("is worse than no record. Run this as them:")
            print()
            for aid in gated:
                version = attestation_registry.get(aid).version
                print(f"  curl -s -X POST -H \"Authorization: Bearer $TEST_API_KEY\" \\")
                print(f"    -H 'Content-Type: application/json' -d '{{\"version\":\"{version}\"}}' \\")
                print(f"    $TEST_BASE_URL/api/v1/attestations/{aid}/accept")

    await engine.dispose()
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(prog="python scripts/seed_test_user.py")
    parser.add_argument("--identifier", default="local-tester")
    parser.add_argument("--plan", default="trial")
    parser.add_argument("--days", type=int, default=365,
                        help="subscription length; 0 for open-ended")
    parser.add_argument("--name", default="e2e testing", help="label for the key")
    parser.add_argument("--new-key", action="store_true",
                        help="issue another key even if a live one exists")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000",
                        help="only used for the lines it prints")
    logging.basicConfig(level="WARNING")
    sys.exit(asyncio.run(main(parser.parse_args())))
