"""Attestation endpoints (OR-40).

The one place the run-only profile lets a user write. It is not authoring and
it is not editing the user: it appends a record of the user's own act, about
themselves, in the same category as cancelling their own run. A template gated
on an attestation is useless without it, since the whole design is that the
user reads the text and agrees to it.

The text itself is read-only here — it ships in config.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import DataResponse
from app.attestations.registry import attestation_registry
from app.attestations.service import (
    AttestationError,
    accept,
    live_records,
    withdraw,
)
from app.db.session import get_db

router = APIRouter(prefix="/attestations", tags=["attestations"])


class AttestationOut(BaseModel):
    id: str
    title: str
    summary: str
    text: str
    version: str
    locale: str
    basis: str
    requirement: str
    # This user's position. accepted_version is what they actually agreed to,
    # which may be older than `version` — that is precisely the case a UI needs
    # to show as "please re-confirm" rather than as "not accepted".
    accepted: bool
    accepted_version: str | None = None
    accepted_at: str | None = None


class AcceptBody(BaseModel):
    # Required, not defaulted: accepting must be a statement about a version the
    # caller actually displayed. See service.accept.
    version: str


def _user_id(request: Request) -> str:
    """The caller's identity, or 400.

    A static deployment key has no identity, so there is no one to record the
    acceptance against. Refusing is honest — silently writing the record
    against nobody would produce a consent trail attached to no person.
    """
    user_id = getattr(request.state, "user_id", None)
    if not user_id:
        raise HTTPException(
            400,
            "Attestations are recorded per user. This request authenticated with "
            "a deployment key, which carries no identity — use a key issued to a "
            "user (python -m app.auth.keys create <identifier>).",
        )
    return user_id


@router.get("", response_model=DataResponse[list[AttestationOut]])
async def list_attestations(request: Request, db: AsyncSession = Depends(get_db)):
    """The catalog, annotated with this caller's position on each."""
    user_id = getattr(request.state, "user_id", None)
    live = await live_records(db, user_id) if user_id else {}

    out: list[AttestationOut] = []
    for item in attestation_registry.all():
        record = live.get(item.id)
        covers = (
            record is not None
            and record.version == item.version
            and record.text_sha256 == item.content_hash
        )
        out.append(AttestationOut(
            id=item.id, title=item.title, summary=item.summary, text=item.text,
            version=item.version, locale=item.locale, basis=item.basis,
            requirement=item.requirement,
            accepted=covers,
            accepted_version=record.version if record else None,
            accepted_at=record.accepted_at.isoformat() if record else None,
        ))
    return DataResponse(data=out)


@router.post("/{attestation_id}/accept", response_model=DataResponse[AttestationOut], status_code=201)
async def accept_attestation(
    attestation_id: str,
    body: AcceptBody,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    user_id = _user_id(request)
    try:
        await accept(db, user_id, attestation_id, body.version)
    except AttestationError as exc:
        # 409, not 422: the request is well-formed, but the catalog moved under
        # it. The client's job is to re-read and try again, not to fix a field.
        raise HTTPException(409, str(exc)) from exc
    await db.commit()
    return await _one(attestation_id, user_id, db)


@router.post("/{attestation_id}/withdraw", response_model=DataResponse[AttestationOut])
async def withdraw_attestation(
    attestation_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Withdraw consent. Templates requiring it stop being runnable at once."""
    user_id = _user_id(request)
    if attestation_registry.get(attestation_id) is None:
        raise HTTPException(404, f"Unknown attestation: {attestation_id!r}")
    await withdraw(db, user_id, attestation_id)
    await db.commit()
    return await _one(attestation_id, user_id, db)


async def _one(attestation_id: str, user_id: str, db: AsyncSession) -> DataResponse:
    item = attestation_registry.get(attestation_id)
    record = (await live_records(db, user_id)).get(attestation_id)
    covers = (
        record is not None
        and record.version == item.version
        and record.text_sha256 == item.content_hash
    )
    return DataResponse(data=AttestationOut(
        id=item.id, title=item.title, summary=item.summary, text=item.text,
        version=item.version, locale=item.locale, basis=item.basis,
        requirement=item.requirement,
        accepted=covers,
        accepted_version=record.version if record else None,
        accepted_at=record.accepted_at.isoformat() if record else None,
    ))
