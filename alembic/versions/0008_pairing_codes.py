"""Device pairing codes.

Revision ID: 0008_pairing_codes
Revises: 0007_token_usage_span
Create Date: 2026-09-18

Short-lived, single-use codes a signed-in device issues so a new one can obtain
its own API key (OR-47). Stored as hashes only.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_pairing_codes"
down_revision = "0007_token_usage_span"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "pairing_codes",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("redeemed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("device_name", sa.String(64), nullable=True),
        sa.Column("redeemed_key_id", sa.String(26), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["redeemed_key_id"], ["api_keys.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_pairing_codes_user_id", "pairing_codes", ["user_id"])
    op.create_index("ix_pairing_codes_code_hash", "pairing_codes", ["code_hash"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_pairing_codes_code_hash", table_name="pairing_codes")
    op.drop_index("ix_pairing_codes_user_id", table_name="pairing_codes")
    op.drop_table("pairing_codes")
