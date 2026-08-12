"""Allow one quote fetch to persist multiple market dates.

Revision ID: 20260811_0006
Revises: 20260811_0005
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0006"
down_revision: str | None = "20260811_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("asset_valuations") as batch:
        batch.add_column(sa.Column("quote_interval", sa.String(length=10)))
    op.execute(
        sa.text(
            "UPDATE asset_valuations SET quote_interval = 'LIVE' "
            "WHERE source IN ('TWELVE_DATA', 'YAHOO_FINANCE')"
        )
    )
    with op.batch_alter_table("asset_valuations") as batch:
        batch.drop_constraint("uq_asset_valuation_quote_replay", type_="unique")
        batch.drop_constraint("ck_asset_valuations_source_provenance", type_="check")
        batch.create_unique_constraint(
            "uq_asset_valuation_quote_replay",
            ["asset_id", "source", "quote_fetched_at", "valued_at"],
        )
        batch.create_check_constraint(
            "quoteinterval",
            "quote_interval IS NULL OR quote_interval IN ('LIVE', 'MONTHLY')",
        )
        batch.create_check_constraint(
            "ck_asset_valuations_source_provenance",
            "(source = 'MANUAL' AND quote_symbol IS NULL AND quote_fetched_at IS NULL AND "
            "quote_interval IS NULL) OR "
            "(source IN ('TWELVE_DATA', 'YAHOO_FINANCE') AND quote_symbol IS NOT NULL AND "
            "quote_fetched_at IS NOT NULL AND quote_interval IS NOT NULL AND "
            "unit_price IS NOT NULL)",
        )
    op.create_index(
        "uq_asset_valuation_monthly",
        "asset_valuations",
        ["asset_id", "source", "valued_at"],
        unique=True,
        sqlite_where=sa.text("quote_interval = 'MONTHLY'"),
    )


def downgrade() -> None:
    connection = op.get_bind()
    monthly_rows = connection.scalar(
        sa.text("SELECT COUNT(*) FROM asset_valuations WHERE quote_interval = 'MONTHLY'")
    )
    if monthly_rows:
        raise RuntimeError("Cannot downgrade while monthly quote history exists")
    duplicate_fetches = connection.scalar(
        sa.text(
            "SELECT COUNT(*) FROM ("
            "SELECT asset_id, source, quote_fetched_at FROM asset_valuations "
            "WHERE quote_fetched_at IS NOT NULL "
            "GROUP BY asset_id, source, quote_fetched_at HAVING COUNT(*) > 1)"
        )
    )
    if duplicate_fetches:
        raise RuntimeError("Cannot downgrade while batched quote history exists")
    op.drop_index("uq_asset_valuation_monthly", table_name="asset_valuations")
    with op.batch_alter_table("asset_valuations") as batch:
        batch.drop_constraint("uq_asset_valuation_quote_replay", type_="unique")
        batch.drop_constraint("ck_asset_valuations_source_provenance", type_="check")
        batch.drop_constraint("quoteinterval", type_="check")
        batch.create_unique_constraint(
            "uq_asset_valuation_quote_replay",
            ["asset_id", "source", "quote_fetched_at"],
        )
        batch.create_check_constraint(
            "ck_asset_valuations_source_provenance",
            "(source = 'MANUAL' AND quote_symbol IS NULL AND quote_fetched_at IS NULL) OR "
            "(source IN ('TWELVE_DATA', 'YAHOO_FINANCE') AND quote_symbol IS NOT NULL AND "
            "quote_fetched_at IS NOT NULL AND unit_price IS NOT NULL)",
        )
        batch.drop_column("quote_interval")
