"""Device pairing (OR-47): sign a new device in without pasting a key.

    signed-in device                         new device
    ────────────────                         ──────────
    POST /pairing          → code, expiry
    shows QR + code  ─────── scan or type ──→ POST /pairing/redeem {code}
    polls GET /pairing/{id}                  ← its own API key

Choices worth knowing:

- **The new device gets its own key**, never a copy of the issuer's. Losing a
  phone means revoking one key, not rotating every device.
- **Codes are 10 Crockford-base32 characters: 50 bits.** Enough that neither
  online guessing (the code expires in minutes) nor offline guessing from a
  leaked hash (a GPU needs days for 2^50 SHA-256) wins inside the window, and
  short enough to type when a camera is not an option. Crockford because it
  drops I, L, O and U — the characters people misread.
- **Redemption is atomic.** A single UPDATE ... WHERE redeemed_at IS NULL claims
  the code, so two devices racing on one code cannot both win.
- **Only one outstanding code per user.** Issuing a new one expires the old,
  which bounds how many live codes exist and matches what the screen shows.
- **Failures are indistinguishable.** Unknown, expired and already-used all read
  the same, so the endpoint is not an oracle for which codes exist.
"""
from __future__ import annotations

import hashlib
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.auth.keys import issue_key
from app.db.models.pairing import PairingCode
from app.db.models.user import User

CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"   # Crockford base32
CODE_LENGTH = 10
TTL = timedelta(minutes=5)
DEVICE_NAME_MAX = 40

# Crockford decoding is forgiving of the look-alikes it removed.
_LOOKALIKES = str.maketrans({"O": "0", "I": "1", "L": "1"})


class PairingError(Exception):
    """A code could not be redeemed. Deliberately says nothing about why."""


def generate_code() -> str:
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def format_code(code: str) -> str:
    """ABCDE-FGHJK: grouped for reading aloud and typing."""
    return f"{code[:5]}-{code[5:]}"


def normalize_code(raw: str) -> str | None:
    """Accept what people actually type: any case, dashes, spaces, look-alikes."""
    if not isinstance(raw, str):
        return None
    cleaned = re.sub(r"[\s\-_.]", "", raw).upper().translate(_LOOKALIKES)
    if len(cleaned) != CODE_LENGTH or any(c not in CODE_ALPHABET for c in cleaned):
        return None
    return cleaned


def hash_code(normalized: str) -> str:
    return hashlib.sha256(normalized.encode("ascii")).hexdigest()


def clean_device_name(raw: str | None) -> str:
    """User-supplied and unauthenticated: strip control characters, cap length."""
    text = unicodedata.normalize("NFC", raw or "")
    text = "".join(ch for ch in text if unicodedata.category(ch)[0] != "C").strip()
    return text[:DEVICE_NAME_MAX] or "device"


@dataclass
class IssuedCode:
    id: str
    code: str            # formatted, shown to the user exactly once
    expires_at: datetime


@dataclass
class Redeemed:
    api_key: str
    key_id: str
    identifier: str


async def create(db: AsyncSession, user_id: str) -> IssuedCode:
    now = datetime.now(timezone.utc)
    await db.execute(
        update(PairingCode)
        .where(
            PairingCode.user_id == user_id,
            PairingCode.redeemed_at.is_(None),
            PairingCode.expires_at > now,
        )
        .values(expires_at=now)
    )
    code = generate_code()
    row = PairingCode(
        id=str(ULID()),
        user_id=user_id,
        code_hash=hash_code(code),
        created_at=now,
        expires_at=now + TTL,
    )
    db.add(row)
    await db.flush()
    return IssuedCode(id=row.id, code=format_code(code), expires_at=row.expires_at)


async def status(db: AsyncSession, pairing_id: str, user_id: str) -> dict | None:
    """The owner's view of a code. None if it is not theirs — not "forbidden",
    so one user cannot probe another's pairing ids."""
    row = await db.get(PairingCode, pairing_id)
    if row is None or row.user_id != user_id:
        return None
    now = datetime.now(timezone.utc)
    if row.redeemed_at is not None:
        state = "redeemed"
    elif row.expires_at <= now:
        state = "expired"
    else:
        state = "pending"
    return {
        "id": row.id,
        "status": state,
        "expires_at": row.expires_at,
        "redeemed_at": row.redeemed_at,
        "device_name": row.device_name,
    }


async def redeem(db: AsyncSession, raw_code: str, device_name: str | None) -> Redeemed:
    normalized = normalize_code(raw_code)
    if normalized is None:
        raise PairingError()

    now = datetime.now(timezone.utc)
    name = clean_device_name(device_name)
    claimed = (
        await db.execute(
            update(PairingCode)
            .where(
                PairingCode.code_hash == hash_code(normalized),
                PairingCode.redeemed_at.is_(None),
                PairingCode.expires_at > now,
            )
            .values(redeemed_at=now, device_name=name)
            .returning(PairingCode.id, PairingCode.user_id)
        )
    ).first()
    if claimed is None:
        raise PairingError()

    user = await db.get(User, claimed.user_id)
    if user is None or user.status != "active":
        # The code is consumed either way: a disabled account's outstanding
        # codes should not stay redeemable until someone re-enables it.
        await db.commit()
        raise PairingError()

    record, plaintext = await issue_key(db, user, name=f"paired: {name}")
    row = await db.get(PairingCode, claimed.id)
    row.redeemed_key_id = record.id
    await db.flush()
    return Redeemed(api_key=plaintext, key_id=record.id, identifier=user.identifier)


async def outstanding(db: AsyncSession, user_id: str) -> list[PairingCode]:
    now = datetime.now(timezone.utc)
    return list((await db.execute(
        select(PairingCode).where(
            PairingCode.user_id == user_id,
            PairingCode.redeemed_at.is_(None),
            PairingCode.expires_at > now,
        )
    )).scalars().all())
