"""Attestation acceptance records.

Revision ID: 0006_user_attestations
Revises: 0005_subscriptions
Create Date: 2026-09-08

Only the acceptance is stored. The text itself is config (OR-40), so
attestation_id is a plain string with no foreign key — there is no table to
reference, and retiring an attestation must leave the historical record
readable rather than blocking the change.

The composite index serves the one query on the hot path: "does this user hold
a live record for this attestation", evaluated at every gated run.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_user_attestations"
down_revision = "0005_subscriptions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_attestations",
        sa.Column("id", sa.String(26), primary_key=True),
        sa.Column("user_id", sa.String(26), nullable=False),
        sa.Column("attestation_id", sa.String(64), nullable=False),
        sa.Column("version", sa.String(32), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("source", sa.String(16), nullable=False, server_default="api"),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("withdrawn_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_user_attestations_user_id", "user_attestations", ["user_id"])
    op.create_index(
        "ix_user_attestations_user_attestation",
        "user_attestations",
        ["user_id", "attestation_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_attestations_user_attestation", table_name="user_attestations")
    op.drop_index("ix_user_attestations_user_id", table_name="user_attestations")
    op.drop_table("user_attestations")
