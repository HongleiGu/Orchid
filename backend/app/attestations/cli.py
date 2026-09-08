"""Attestation record inspection (OR-40).

    docker compose exec backend python -m app.attestations.cli catalog
    docker compose exec backend python -m app.attestations.cli show alice
    docker compose exec backend python -m app.attestations.cli withdraw alice securities_advisory

There is deliberately no `grant`. An operator recording acceptance on a user's
behalf would produce a consent record for an act that did not happen, which is
worse than no record at all — the whole evidentiary value is that the user did
it themselves. Acceptance goes through POST /api/v1/attestations/{id}/accept.

Withdrawal is the reverse and is a legitimate operator action: revoking a
capability from someone found not to qualify does not require their agreement.
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.attestations.registry import attestation_registry, load_attestations
from app.attestations.service import history, live_records, withdraw
from app.db.models.user import User

logger = logging.getLogger(__name__)


async def _cli(argv: list[str]) -> int:
    import argparse

    from app.db.session import AsyncSessionLocal, engine

    # See app/auth/keys.py: echo is a flag, not a log level.
    engine.echo = False
    load_attestations()

    parser = argparse.ArgumentParser(prog="python -m app.attestations.cli")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("catalog", help="the attestations this deployment defines")

    p_show = sub.add_parser("show", help="a user's full record, newest first")
    p_show.add_argument("identifier")

    p_wd = sub.add_parser("withdraw", help="withdraw a user's acceptance")
    p_wd.add_argument("identifier")
    p_wd.add_argument("attestation_id")

    args = parser.parse_args(argv)

    if args.command == "catalog":
        items = attestation_registry.all()
        if not items:
            print("no attestations defined")
            return 0
        for item in items:
            print(f"{item.id}  v{item.version}  [{item.locale}]  {item.title}")
            print(f"  requirement : {item.requirement}")
            print(f"  basis       : {item.basis or '(none recorded)'}")
            print(f"  sha256      : {item.content_hash}")
            print(f"  summary     : {item.summary}")
            print()
        return 0

    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(select(User).where(User.identifier == args.identifier))
        ).scalar_one_or_none()
        if user is None:
            print(f"no such user: {args.identifier!r}")
            return 1

        if args.command == "show":
            rows = await history(db, user.id)
            if not rows:
                print(f"{user.identifier} has accepted nothing")
                return 0
            live = await live_records(db, user.id)
            print(f"{user.identifier} ({user.id})\n")
            for row in rows:
                current = attestation_registry.get(row.attestation_id)
                if row.withdrawn_at:
                    state = f"withdrawn {row.withdrawn_at:%Y-%m-%d}"
                elif current is None:
                    state = "attestation retired from the catalog"
                elif live.get(row.attestation_id) is not row:
                    state = "superseded by a later acceptance"
                elif row.version != current.version:
                    state = f"stale — catalog is now v{current.version}"
                elif row.text_sha256 != current.content_hash:
                    state = "stale — text edited without a version bump"
                else:
                    state = "in force"
                print(f"  {row.attestation_id:24} v{row.version:4} "
                      f"{row.accepted_at:%Y-%m-%d %H:%M}  via {row.source:4}  {state}")
                print(f"  {'':24} sha256 {row.text_sha256}")
            return 0

        if args.command == "withdraw":
            count = await withdraw(db, user.id, args.attestation_id)
            await db.commit()
            print(f"withdrew {count} record(s)")
            return 0

    return 1


if __name__ == "__main__":
    import asyncio
    import sys

    logging.basicConfig(level="WARNING")
    sys.exit(asyncio.run(_cli(sys.argv[1:])))
