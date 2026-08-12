"""Add detached transaction deletion audit.

Revision ID: 20260810_0002
Revises: 20260809_0001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260810_0002"
down_revision: str | None = "20260809_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transaction_deletions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("transaction_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(80), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_transaction_deletions_transaction_id",
        "transaction_deletions",
        ["transaction_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transaction_deletions_transaction_id",
        table_name="transaction_deletions",
    )
    op.drop_table("transaction_deletions")
