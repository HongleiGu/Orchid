"""Vault project ownership.

Revision ID: 0009_vault_owner
Revises: 0008_pairing_codes
Create Date: 2026-09-18

One row per owned project (OR-48). No backfill: existing projects stay
unowned, which means an operator (static key) still sees them and identified
users see only what they create from here on — backwards-compatible for a
single-operator deployment.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_vault_owner"
down_revision = "0008_pairing_codes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vault_owners",
        sa.Column("project", sa.String(256), primary_key=True),
        sa.Column("user_id", sa.String(26), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_vault_owners_user_id", "vault_owners", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_vault_owners_user_id", table_name="vault_owners")
    op.drop_table("vault_owners")
