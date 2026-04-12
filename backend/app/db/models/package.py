from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class InstalledPackage(Base):
    __tablename__ = "installed_packages"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    npm_name: Mapped[str] = mapped_column(String(256), nullable=False, unique=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="unknown")
    pkg_type: Mapped[str] = mapped_column(String(16), nullable=False)  # skill | tool | mcp
    registered_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    parameters: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    installed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
