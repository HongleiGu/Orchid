from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")

    # "single" | "dag" | "group"
    workflow_type: Mapped[str] = mapped_column(String(16), nullable=False, default="single")
    # For "single": {} — agent_id field is used.
    # For "dag":    {"nodes": [...], "edges": [...], "entry": "node_name"}
    # For "group":  {"orchestrator_id": "...", "worker_ids": [...],
    #                "max_turns_per_agent": 5, "max_total_turns": 20}
    workflow_config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    # Used when workflow_type == "single"
    agent_id: Mapped[str | None] = mapped_column(
        String(26), ForeignKey("agents.id", ondelete="SET NULL")
    )
    inputs: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    cron_expr: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="idle")
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )
