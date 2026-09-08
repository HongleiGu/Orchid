"""Attribute runs and token usage to a user.

Revision ID: 0004_user_attribution
Revises: 0003_users_and_api_keys
Create Date: 2026-09-08

Both columns are nullable. Existing rows pre-date user attribution, and a
request authenticated with a static AUTH_API_KEYS key carries no identity at
all, so NULL is a legitimate ongoing state rather than only a backfill gap.

user_id is denormalised onto token_usage rather than reached through runs.
Quota is checked before every LLM call, so that lookup is the hot path — an
indexed filter on token_usage beats joining through runs for a user with
thousands of them. It also leaves usage rows self-describing for later export.

budget_limits needs no change: it already carries scope_type/scope_id, so a
per-user quota is a new scope value rather than a new column.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_user_attribution"
down_revision = "0003_users_and_api_keys"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("runs", sa.Column("user_id", sa.String(26), nullable=True))
    op.create_index("ix_runs_user_id", "runs", ["user_id"])
    op.create_foreign_key(
        "fk_runs_user_id", "runs", "users", ["user_id"], ["id"], ondelete="SET NULL"
    )

    op.add_column("token_usage", sa.Column("user_id", sa.String(26), nullable=True))
    op.create_index("ix_token_usage_user_id", "token_usage", ["user_id"])
    # SET NULL, not CASCADE: deleting a user must not erase the record of what
    # was spent on their behalf.
    op.create_foreign_key(
        "fk_token_usage_user_id", "token_usage", "users", ["user_id"], ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_token_usage_user_id", "token_usage", type_="foreignkey")
    op.drop_index("ix_token_usage_user_id", table_name="token_usage")
    op.drop_column("token_usage", "user_id")

    op.drop_constraint("fk_runs_user_id", "runs", type_="foreignkey")
    op.drop_index("ix_runs_user_id", table_name="runs")
    op.drop_column("runs", "user_id")
