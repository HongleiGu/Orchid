"""Device pairing codes (OR-47).

A signed-in device asks for a short-lived code; a new device redeems it and is
issued its own API key. Only the SHA-256 of the code is stored — the same rule
as API keys — so a database read does not yield codes that could be redeemed.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # Set exactly once, by the redemption that wins — see service.redeem.
    redeemed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Kept so the owner can see which device took the code, and so the key it
    # produced can be found and revoked later.
    device_name: Mapped[str | None] = mapped_column(String(64))
    redeemed_key_id: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("api_keys.id", ondelete="SET NULL")
    )
