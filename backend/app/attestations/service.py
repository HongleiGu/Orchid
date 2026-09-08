"""Resolving template requirements against a user's attestation record (OR-40).

Every decision here fails closed. A requirement whose scheme is not understood,
an attestation missing from the catalog, a record for a superseded version, a
record whose stored hash no longer matches the shipped text — all are unmet.
The alternative, treating "I cannot tell" as "permitted", is how a gate that
exists for a regulator ends up open.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from ulid import ULID

from app.attestations.registry import (
    REQUIREMENT_SCHEME,
    Attestation,
    attestation_registry,
)
from app.db.models.attestation import UserAttestation

logger = logging.getLogger(__name__)


class AttestationError(Exception):
    """Acceptance was refused. The message is safe to show the user."""


async def live_records(db: AsyncSession, user_id: str) -> dict[str, UserAttestation]:
    """The user's most recent non-withdrawn record per attestation.

    Most recent rather than any: a user who withdraws and re-accepts has two
    live-looking rows only if withdrawal is ignored, and the newest row is the
    one that describes their current position.
    """
    rows = (
        await db.execute(
            select(UserAttestation)
            .where(
                UserAttestation.user_id == user_id,
                UserAttestation.withdrawn_at.is_(None),
            )
            .order_by(UserAttestation.accepted_at.desc())
        )
    ).scalars().all()

    latest: dict[str, UserAttestation] = {}
    for row in rows:
        latest.setdefault(row.attestation_id, row)
    return latest


def _record_covers(record: UserAttestation, current: Attestation) -> bool:
    """Whether an acceptance still covers what the catalog now says.

    Version mismatch is the ordinary case: the text was revised and the user
    must agree again. A hash mismatch on a matching version is the case nobody
    intends — the text was edited without a bump — and is logged loudly,
    because from the user's side it presents as an inexplicable lockout.
    """
    if record.version != current.version:
        return False
    if record.text_sha256 != current.content_hash:
        logger.error(
            "Attestation %r version %s was edited without a version bump: stored "
            "acceptances no longer match the shipped text and are being treated "
            "as stale. Bump `version` in the catalog to make this a deliberate "
            "re-acceptance.",
            current.id, current.version,
        )
        return False
    return True


async def is_satisfied(db: AsyncSession, user_id: str | None, attestation_id: str) -> bool:
    if user_id is None:
        return False
    current = attestation_registry.get(attestation_id)
    if current is None:
        return False
    record = (await live_records(db, user_id)).get(attestation_id)
    return record is not None and _record_covers(record, current)


async def unmet_requirements(
    db: AsyncSession, user_id: str | None, requires: list[str]
) -> list[str]:
    """Which of a template's declared requirements this user does not meet.

    An anonymous caller — a static AUTH_API_KEYS deployment key — is exempt.
    That key is an operator credential, not a user credential: there is no user
    row to hold a record, and the operator is the licensee who accepted terms
    out of band. It matches how plans already treat an anonymous caller, and it
    is the reason a multi-tenant deployment must issue per-user keys (OR-37)
    rather than sharing the deployment key: with no identity there is no
    attestation, no quota and no plan.
    """
    if not requires:
        return []
    if user_id is None:
        return []

    live = await live_records(db, user_id)

    unmet: list[str] = []
    for requirement in requires:
        scheme, _, ident = requirement.partition(":")
        if scheme != REQUIREMENT_SCHEME or not ident:
            # A typo in a template's `requires` must not open the gate. The
            # template becomes unrunnable, which surfaces as a bug report.
            logger.error(
                "Template requirement %r is not understood — treating it as "
                "unmet. Supported: '%s:<id>'", requirement, REQUIREMENT_SCHEME,
            )
            unmet.append(requirement)
            continue

        current = attestation_registry.get(ident)
        if current is None:
            logger.error(
                "Template requires attestation %r, which is not in the catalog "
                "— treating it as unmet.", ident,
            )
            unmet.append(requirement)
            continue

        record = live.get(ident)
        if record is None or not _record_covers(record, current):
            unmet.append(requirement)

    return unmet


async def accept(
    db: AsyncSession, user_id: str, attestation_id: str, version: str, source: str = "api"
) -> UserAttestation:
    """Record that a user accepted an attestation.

    The caller must echo back the version it displayed. A mismatch means the
    text changed between the page being rendered and the button being pressed,
    so what the user actually read is not what is now current — recording that
    as consent to the current text would be a lie in the record.
    """
    current = attestation_registry.get(attestation_id)
    if current is None:
        raise AttestationError(f"Unknown attestation: {attestation_id!r}")
    if version != current.version:
        raise AttestationError(
            f"Attestation {attestation_id!r} is now at version {current.version}, "
            f"not {version!r}. Re-read the current text and accept that."
        )

    record = UserAttestation(
        id=str(ULID()),
        user_id=user_id,
        attestation_id=attestation_id,
        version=current.version,
        text_sha256=current.content_hash,
        source=source,
    )
    db.add(record)
    await db.flush()
    logger.info(
        "Attestation %s v%s accepted by user %s via %s",
        attestation_id, current.version, user_id, source,
    )
    return record


async def withdraw(db: AsyncSession, user_id: str, attestation_id: str) -> int:
    """Withdraw a user's acceptance. Returns how many records were closed.

    Marks rather than deletes: the fact that consent was given and later
    withdrawn is itself part of the record.
    """
    rows = (
        await db.execute(
            select(UserAttestation).where(
                UserAttestation.user_id == user_id,
                UserAttestation.attestation_id == attestation_id,
                UserAttestation.withdrawn_at.is_(None),
            )
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    for row in rows:
        row.withdrawn_at = now
    await db.flush()
    return len(rows)


async def history(db: AsyncSession, user_id: str) -> list[UserAttestation]:
    """Every record for a user, newest first — the evidentiary view."""
    return list(
        (
            await db.execute(
                select(UserAttestation)
                .where(UserAttestation.user_id == user_id)
                .order_by(UserAttestation.accepted_at.desc())
            )
        ).scalars().all()
    )
