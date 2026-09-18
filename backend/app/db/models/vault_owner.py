"""Vault project ownership (OR-48).

The vault is a shared directory, so ownership is recorded here rather than on
disk: one row per project, naming the user who created it. Absence of a row
means unowned — legacy content, or a project written by an operator (static)
key that carries no identity. Ownership is claimed first-write-wins and is
per project, matching how the vault is organised (one project = one workflow's
outputs).

`project` is the primary key: project names are already the unique top-level
namespace on disk, and the string stored here must be exactly the directory
name the vault API lists, so the two are kept in lockstep by the sanitisers in
app/vault/ownership.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class VaultOwner(Base):
    __tablename__ = "vault_owners"

    project: Mapped[str] = mapped_column(String(256), primary_key=True)
    # CASCADE: if the user is deleted, the project becomes unowned (the row
    # goes), which hides it from every identified user and leaves it visible
    # only to an operator — the safe direction.
    user_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(timezone.utc)
    )
