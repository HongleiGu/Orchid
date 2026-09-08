"""Plan membership.

Revision ID: 0005_subscriptions
Revises: 0004_user_attribution
Create Date: 2026-09-08

Only the assignment is stored. Plan definitions are config (OR-38), so
plan_id is a plain string with no foreign key — there is no table to reference,
and removing a plan from the catalog must leave existing rows readable rather
than blocking the change.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_subscriptions"
down_revision = "0004_user_attribution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), nullable=False),
        sa.Column("plan_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_subscriptions_user_id", "subscriptions", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_subscriptions_user_id", table_name="subscriptions")
    op.drop_table("subscriptions")
