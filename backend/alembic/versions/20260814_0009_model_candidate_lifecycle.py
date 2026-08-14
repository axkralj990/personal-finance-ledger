"""Add candidate and retired model lifecycle.

Revision ID: 20260814_0009
Revises: 20260813_0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260814_0009"
down_revision: str | None = "20260813_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("model_versions", sa.Column("retired_at", sa.DateTime(timezone=True)))
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE model_versions SET activated_at = created_at "
            "WHERE activated_at IS NULL"
        )
    )
    connection.execute(
        sa.text(
            "UPDATE model_versions SET retired_at = created_at "
            "WHERE is_active = 0 AND id NOT IN ("
            "SELECT id FROM model_versions WHERE is_active = 0 "
            "ORDER BY activated_at DESC, created_at DESC LIMIT 1)"
        )
    )
    op.create_index(
        "uq_one_model_candidate",
        "model_versions",
        ["is_active"],
        unique=True,
        sqlite_where=sa.text(
            "is_active = 0 AND activated_at IS NULL AND retired_at IS NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_one_model_candidate", table_name="model_versions")
    op.drop_column("model_versions", "retired_at")
