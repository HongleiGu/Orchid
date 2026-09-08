"""API key issuing and verification (OR-37).

Keys are 32 bytes of CSPRNG output, shown once at creation and stored only as a
SHA-256 hash. The hash is indexed, so verification is one lookup.

On the hash choice: a slow KDF (bcrypt, argon2) is right for passwords, which
are low-entropy and guessable. An API key is 256 bits of randomness — there is
no dictionary to attack, and a slow hash would force a scan of every row per
request, since you cannot look up a salted hash. SHA-256 is the correct trade
here, and this is the reasoning to point at when someone asks why it is not
bcrypt.

Management is a CLI rather than an HTTP surface. There is no admin UI yet, and
adding write endpoints would be something the run-only profile then has to
block. Run it against a deployment with:

    docker compose exec backend python -m app.auth.keys create <identifier> --name laptop
    docker compose exec backend python -m app.auth.keys list
    docker compose exec backend python -m app.auth.keys revoke <key-id>
"""
from __future__ import annotations

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.db.models.user import ApiKey, User

logger = logging.getLogger(__name__)

KEY_PREFIX = "orc_"
_PREFIX_DISPLAY_LEN = 12
# How stale last_used_at may get. Writing on every request would add a write to
# every authenticated call for information nobody needs to the second.
_LAST_USED_RESOLUTION = timedelta(minutes=5)


def generate_key() -> str:
    return KEY_PREFIX + secrets.token_urlsafe(32)


def hash_key(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()


async def create_user(db: AsyncSession, identifier: str, display_name: str = "") -> User:
    user = User(id=str(ULID()), identifier=identifier, display_name=display_name)
    db.add(user)
    await db.flush()
    return user


async def get_or_create_user(db: AsyncSession, identifier: str) -> User:
    existing = (
        await db.execute(select(User).where(User.identifier == identifier))
    ).scalar_one_or_none()
    return existing or await create_user(db, identifier)


async def issue_key(db: AsyncSession, user: User, name: str = "") -> tuple[ApiKey, str]:
    """Create a key. Returns the record and the plaintext, which is never
    recoverable afterwards."""
    plaintext = generate_key()
    record = ApiKey(
        id=str(ULID()),
        user_id=user.id,
        name=name,
        key_hash=hash_key(plaintext),
        prefix=plaintext[:_PREFIX_DISPLAY_LEN],
    )
    db.add(record)
    await db.flush()
    return record, plaintext


async def verify_key(db: AsyncSession, plaintext: str) -> User | None:
    """Resolve a presented key to its user, or None.

    Rejects revoked keys and disabled users. Both checks matter: revoking one
    key should not require disabling the user, and disabling a user must stop
    every key they hold at once.
    """
    if not plaintext:
        return None

    record = (
        await db.execute(select(ApiKey).where(ApiKey.key_hash == hash_key(plaintext)))
    ).scalar_one_or_none()
    if record is None or record.revoked_at is not None:
        return None

    user = await db.get(User, record.user_id)
    if user is None or user.status != "active":
        return None

    now = datetime.now(timezone.utc)
    if record.last_used_at is None or now - record.last_used_at > _LAST_USED_RESOLUTION:
        record.last_used_at = now
        await db.flush()
    return user


async def revoke_key(db: AsyncSession, key_id: str) -> bool:
    record = await db.get(ApiKey, key_id)
    if record is None or record.revoked_at is not None:
        return False
    record.revoked_at = datetime.now(timezone.utc)
    await db.flush()
    return True


# ── CLI ───────────────────────────────────────────────────────────────────────

async def _cli(argv: list[str]) -> int:
    import argparse

    from app.db.session import AsyncSessionLocal

    from app.db.session import engine

    # echo is checked as a flag by SQLAlchemy's InstanceLogger, not via the
    # logging level, so setting a level cannot suppress it. The engine has
    # echo on in development, which would bury the one line an operator
    # needs — the key itself.
    engine.echo = False

    parser = argparse.ArgumentParser(prog="python -m app.auth.keys")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="issue a key for a user, creating the user if needed")
    p_create.add_argument("identifier")
    p_create.add_argument("--name", default="")

    sub.add_parser("list", help="list keys")

    p_revoke = sub.add_parser("revoke", help="revoke a key by id")
    p_revoke.add_argument("key_id")

    args = parser.parse_args(argv)

    async with AsyncSessionLocal() as db:
        if args.command == "create":
            user = await get_or_create_user(db, args.identifier)
            record, plaintext = await issue_key(db, user, args.name)
            await db.commit()
            print(f"user      {user.identifier} ({user.id})")
            print(f"key id    {record.id}")
            print(f"key       {plaintext}")
            print("\nStore it now — only the hash is kept, so it cannot be shown again.")
            return 0

        if args.command == "list":
            rows = (
                await db.execute(
                    select(ApiKey, User).join(User, ApiKey.user_id == User.id)
                    .order_by(ApiKey.created_at)
                )
            ).all()
            if not rows:
                print("no keys")
                return 0
            print(f"{'KEY ID':28} {'USER':24} {'NAME':16} {'PREFIX':14} STATUS")
            for key, user in rows:
                status = "revoked" if key.revoked_at else (
                    "disabled-user" if user.status != "active" else "active"
                )
                print(f"{key.id:28} {user.identifier:24} {key.name:16} {key.prefix:14} {status}")
            return 0

        if args.command == "revoke":
            ok = await revoke_key(db, args.key_id)
            await db.commit()
            print("revoked" if ok else "not found, or already revoked")
            return 0 if ok else 1

    return 1


if __name__ == "__main__":
    import asyncio
    import sys

    logging.basicConfig(level="WARNING")
    sys.exit(asyncio.run(_cli(sys.argv[1:])))
