"""Add priority + runtime_params to runs, default_priority to tasks.

Revision ID: 0001_priority_queue
Revises:
Create Date: 2026-04-12

Introduces the DB-backed sequential queue: a single consumer claims pending
Run rows ordered by (priority DESC, created_at ASC). runtime_params survives
restarts so a queued run with custom inputs is recoverable.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0001_priority_queue"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("runs") as batch:
        batch.add_column(sa.Column("priority", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("runtime_params", sa.JSON(), nullable=False, server_default="{}"))

    with op.batch_alter_table("tasks") as batch:
        batch.add_column(sa.Column("default_priority", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("input_schema", sa.JSON(), nullable=False, server_default="[]"))

    # Index for the consumer's claim query
    op.create_index(
        "ix_runs_pending_claim",
        "runs",
        ["status", "priority", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_runs_pending_claim", table_name="runs")
    with op.batch_alter_table("tasks") as batch:
        batch.drop_column("input_schema")
        batch.drop_column("default_priority")
    with op.batch_alter_table("runs") as batch:
        batch.drop_column("runtime_params")
        batch.drop_column("priority")
