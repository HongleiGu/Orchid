"""Per-span cost attribution.

Revision ID: 0007_token_usage_span
Revises: 0006_user_attestations
Create Date: 2026-09-09

Nullable with no backfill, deliberately. Rows written before this migration
were never associated with a span and no value could be invented for them
without guessing; NULL says "not attributed", which is true, and the run detail
reports that spend as unattributed rather than hiding it.

No foreign key: spans have no table. They are reconstructed from the immutable
run_events log, so there is nothing to reference and nothing to cascade.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_token_usage_span"
down_revision = "0006_user_attestations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("token_usage") as batch:
        batch.add_column(sa.Column("span_id", sa.String(26), nullable=True))

    # The rollup query groups a single run's usage by span, so the composite
    # index is what that reads — span_id alone would not narrow to the run.
    op.create_index(
        "ix_token_usage_run_span", "token_usage", ["run_id", "span_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_token_usage_run_span", table_name="token_usage")
    with op.batch_alter_table("token_usage") as batch:
        batch.drop_column("span_id")
