"""Plan membership (OR-38, layer 3).

Only the *assignment* lives here. The plan definitions themselves are config,
so a compromised database can move a user to an existing tier but cannot invent
one with capability the deployment never defined.

plan_id is a plain string, deliberately not a foreign key: plans are config, so
there is no table to reference, and a plan removed from the catalog must leave
the row readable rather than blocking the delete.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Matches a Plan.id from the config catalog. Unresolvable ids fall back to
    # the ceiling rather than failing closed, so deleting a plan degrades to
    # "no tier" instead of locking its subscribers out.
    plan_id: Mapped[str] = mapped_column(String(64), nullable=False)
    # "active" | "cancelled". Expiry is period_end, kept separate so a cancelled
    # subscription can still run out its paid period.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")

    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # NULL = open-ended, for a 私有化部署 licence with no renewal cycle.
    period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
