"""Attestation acceptance records (OR-40).

Evidentiary rows: who accepted what, which version of the text, and when. Rows
are append-only in spirit — a withdrawal sets withdrawn_at rather than deleting,
because "this person accepted, then withdrew" and "this person never accepted"
are different facts and only one of them is a record.

Deliberately *not* stored: IP address and user agent. They would strengthen the
evidence, but they are personal information collected for every acceptance, and
the ticket's requirement — who, what version, when — is met without them. Add
them only if a real compliance requirement asks, rather than by default.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class UserAttestation(Base):
    __tablename__ = "user_attestations"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Matches an Attestation.id in the config catalog. A plain string, as with
    # subscriptions.plan_id: the catalog is config, so there is no table to
    # reference, and retiring an attestation must leave the historical record
    # readable rather than blocking the change.
    attestation_id: Mapped[str] = mapped_column(String(64), nullable=False)

    # What was actually agreed to. Version is what a person reasons about;
    # text_sha256 is what makes the claim checkable years later, and catches an
    # edit that skipped the version bump.
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    text_sha256: Mapped[str] = mapped_column(String(64), nullable=False)

    # How the record was created: "api" (the user themselves) or "cli" (an
    # operator). Worth distinguishing — only the first is the user's own act.
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="api")

    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    # NULL = still in force.
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
