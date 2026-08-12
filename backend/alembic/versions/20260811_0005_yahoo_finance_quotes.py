"""Add Yahoo Finance quote provenance.

Revision ID: 20260811_0005
Revises: 20260811_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0005"
down_revision: str | None = "20260811_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("asset_valuations") as batch:
        batch.drop_constraint("valuationsource", type_="check")
        batch.drop_constraint("ck_asset_valuations_source_provenance", type_="check")
        batch.alter_column(
            "source",
            existing_type=sa.String(length=11),
            type_=sa.String(length=20),
            existing_nullable=False,
        )
        batch.create_check_constraint(
            "valuationsource",
            "source IN ('MANUAL', 'TWELVE_DATA', 'YAHOO_FINANCE')",
        )
        batch.create_check_constraint(
            "ck_asset_valuations_source_provenance",
            "(source = 'MANUAL' AND quote_symbol IS NULL AND quote_fetched_at IS NULL) OR "
            "(source IN ('TWELVE_DATA', 'YAHOO_FINANCE') AND quote_symbol IS NOT NULL AND "
            "quote_fetched_at IS NOT NULL AND unit_price IS NOT NULL)",
        )


def downgrade() -> None:
    connection = op.get_bind()
    yahoo_rows = connection.scalar(
        sa.text("SELECT COUNT(*) FROM asset_valuations WHERE source = 'YAHOO_FINANCE'")
    )
    if yahoo_rows:
        raise RuntimeError("Cannot downgrade while Yahoo Finance valuations exist")
    with op.batch_alter_table("asset_valuations") as batch:
        batch.drop_constraint("valuationsource", type_="check")
        batch.drop_constraint("ck_asset_valuations_source_provenance", type_="check")
        batch.alter_column(
            "source",
            existing_type=sa.String(length=20),
            type_=sa.String(length=11),
            existing_nullable=False,
        )
        batch.create_check_constraint(
            "valuationsource",
            "source IN ('MANUAL', 'TWELVE_DATA')",
        )
        batch.create_check_constraint(
            "ck_asset_valuations_source_provenance",
            "(source = 'MANUAL' AND quote_symbol IS NULL AND quote_fetched_at IS NULL) OR "
            "(source = 'TWELVE_DATA' AND quote_symbol IS NOT NULL AND "
            "quote_fetched_at IS NOT NULL AND unit_price IS NOT NULL)",
        )
