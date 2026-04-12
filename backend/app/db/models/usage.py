from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TokenUsage(Base):
    """Per-LLM-call token usage record. One row per model_client.complete() call."""
    __tablename__ = "token_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        String(26), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    agent_name: Mapped[str] = mapped_column(String(128), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Estimated cost in USD (based on known model pricing)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    ts: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )


class BudgetLimit(Base):
    """Budget limits. scope_type + scope_id identify what the limit applies to."""
    __tablename__ = "budget_limits"

    id: Mapped[str] = mapped_column(String(26), primary_key=True)
    # "global" | "agent" | "task"
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # For "global": "global". For "agent"/"task": the entity's ID.
    scope_id: Mapped[str] = mapped_column(String(26), nullable=False)
    # Limits (null = no limit for that dimension)
    max_tokens_per_run: Mapped[int | None] = mapped_column(Integer)
    max_cost_per_run: Mapped[float | None] = mapped_column(Float)
    max_cost_per_day: Mapped[float | None] = mapped_column(Float)
    max_cost_per_month: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
