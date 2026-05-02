"""Add span_id + parent_span_id to run_events.

Revision ID: 0002_span_columns
Revises: 0001_priority_queue
Create Date: 2026-05-02

Span tree links each event to the unit of work that emitted it. Existing
rows get NULL for both columns — they pre-date span tracking and that's
fine, the tree query just shows them as orphan events.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_span_columns"
down_revision = "0001_priority_queue"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("run_events") as batch:
        batch.add_column(sa.Column("span_id", sa.String(length=26), nullable=True))
        batch.add_column(sa.Column("parent_span_id", sa.String(length=26), nullable=True))

    op.create_index("ix_run_events_span_id", "run_events", ["span_id"])


def downgrade() -> None:
    op.drop_index("ix_run_events_span_id", table_name="run_events")
    with op.batch_alter_table("run_events") as batch:
        batch.drop_column("parent_span_id")
        batch.drop_column("span_id")
