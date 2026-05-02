from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    task_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False
    )
    agent_id: Mapped[str | None] = mapped_column(String(26))
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    # Higher = runs sooner. Ties broken by created_at ASC.
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Runtime params merged with task.inputs at execution time.
    runtime_params: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    model_used: Mapped[str | None] = mapped_column(String(128))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    result: Mapped[dict | None] = mapped_column(JSON)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class RunEvent(Base):
    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    agent: Mapped[str | None] = mapped_column(String(128))
    # Span-tree linkage — populated for AGENT_START / AGENT_END / TOOL_CALL /
    # TOOL_RESULT / COLLAB_ROUTE. Nullable so pre-span events still validate.
    span_id: Mapped[str | None] = mapped_column(String(26), index=True)
    parent_span_id: Mapped[str | None] = mapped_column(String(26))
    payload: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
