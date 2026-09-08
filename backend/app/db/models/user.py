"""Users and API keys (OR-37).

These live in the database rather than config because revocation has to take
effect without a restart — the one thing config cannot do. The capability
ceiling stays in config; this is identity, which is a different concern.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    # Identifier the operator recognises. Not necessarily an email — a
    # 私有化部署 customer may key on a staff id.
    identifier: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # "active" | "disabled". Disabling stops every key at once, without
    # revoking them individually.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class ApiKey(Base):
    __tablename__ = "api_keys"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # What this key is for, so a human can decide which to revoke.
    name: Mapped[str] = mapped_column(String(128), nullable=False, default="")

    # SHA-256 of the key. Indexed and unique so verification is a single lookup
    # rather than a scan. A slow KDF (bcrypt/argon2) would defeat that and buys
    # nothing here: keys are 32 bytes of CSPRNG output, so there is no
    # dictionary to attack — unlike a password.
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    # Leading characters of the key, kept in clear so the UI can show which key
    # is which without ever storing the secret.
    prefix: Mapped[str] = mapped_column(String(16), nullable=False, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    # Coarse: updated at most once every few minutes, so a busy key does not
    # add a write to every request.
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Set rather than deleted, so an audit trail survives revocation.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    # Reserved for OR-39's per-user quota; unused for now.
    request_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
