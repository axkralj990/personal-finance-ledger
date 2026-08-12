"""Add portfolio assets, valuations, and audit events.

Revision ID: 20260811_0003
Revises: 20260810_0002
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0003"
down_revision: str | None = "20260810_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column(
            "asset_type",
            sa.Enum(
                "BANK_CASH",
                "BROKERAGE_CASH",
                "ETF",
                "STOCK",
                "FIXED_ASSET",
                "OTHER",
                name="assettype",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("acquisition_date", sa.Date(), nullable=False),
        sa.Column("quantity", sa.String(80)),
        sa.Column("cost_basis_native_minor", sa.Integer()),
        sa.Column("cost_basis_eur_minor", sa.Integer()),
        sa.Column("quote_symbol", sa.String(40)),
        sa.Column("quote_exchange", sa.String(80)),
        sa.Column("quote_mic_code", sa.String(12)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("length(currency) = 3", name="ck_assets_currency_length"),
        sa.CheckConstraint("revision >= 1", name="ck_assets_revision"),
        sa.CheckConstraint(
            "(cost_basis_native_minor IS NULL AND cost_basis_eur_minor IS NULL) OR "
            "(cost_basis_native_minor >= 0 AND cost_basis_eur_minor >= 0)",
            name="ck_assets_cost_basis",
        ),
        sa.CheckConstraint(
            "asset_type NOT IN ('BANK_CASH', 'BROKERAGE_CASH') OR "
            "(cost_basis_native_minor IS NULL AND cost_basis_eur_minor IS NULL)",
            name="ck_assets_cash_without_cost_basis",
        ),
        sa.CheckConstraint(
            "(quote_symbol IS NULL AND quote_exchange IS NULL AND quote_mic_code IS NULL) OR "
            "(asset_type IN ('ETF', 'STOCK') AND quote_symbol IS NOT NULL AND "
            "(quote_exchange IS NOT NULL OR quote_mic_code IS NOT NULL))",
            name="ck_assets_quote_configuration",
        ),
        sa.CheckConstraint(
            "(is_active = 1 AND archived_at IS NULL) OR "
            "(is_active = 0 AND archived_at IS NOT NULL)",
            name="ck_assets_archive_state",
        ),
    )
    op.create_index("ix_assets_asset_type", "assets", ["asset_type"])
    op.create_index("ix_assets_is_active", "assets", ["is_active"])

    op.create_table(
        "asset_valuations",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "asset_id",
            sa.String(36),
            sa.ForeignKey("assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("valued_at", sa.Date(), nullable=False),
        sa.Column("native_value_minor", sa.Integer(), nullable=False),
        sa.Column("eur_value_minor", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.String(80)),
        sa.Column("unit_price", sa.String(80)),
        sa.Column("cost_basis_native_minor", sa.Integer()),
        sa.Column("cost_basis_eur_minor", sa.Integer()),
        sa.Column(
            "source",
            sa.Enum(
                "MANUAL",
                "TWELVE_DATA",
                name="valuationsource",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("quote_symbol", sa.String(40)),
        sa.Column("quote_exchange", sa.String(80)),
        sa.Column("quote_mic_code", sa.String(12)),
        sa.Column("quote_name", sa.String(200)),
        sa.Column("quote_fetched_at", sa.DateTime(timezone=True)),
        sa.Column("fx_source", sa.String(20), nullable=False),
        sa.Column("fx_rate_to_eur", sa.String(80), nullable=False),
        sa.Column("fx_rate_date", sa.Date(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("native_value_minor >= 0", name="ck_asset_valuations_native_value"),
        sa.CheckConstraint("eur_value_minor >= 0", name="ck_asset_valuations_eur_value"),
        sa.CheckConstraint("length(fx_rate_to_eur) > 0", name="ck_asset_valuations_fx_rate"),
        sa.CheckConstraint(
            "(cost_basis_native_minor IS NULL AND cost_basis_eur_minor IS NULL) OR "
            "(cost_basis_native_minor >= 0 AND cost_basis_eur_minor >= 0)",
            name="ck_asset_valuations_cost_basis",
        ),
        sa.CheckConstraint(
            "(source = 'MANUAL' AND quote_symbol IS NULL AND quote_fetched_at IS NULL) OR "
            "(source = 'TWELVE_DATA' AND quote_symbol IS NOT NULL AND "
            "quote_fetched_at IS NOT NULL AND unit_price IS NOT NULL)",
            name="ck_asset_valuations_source_provenance",
        ),
    )
    op.create_index(
        "ix_asset_valuations_asset_id_valued_at",
        "asset_valuations",
        ["asset_id", "valued_at"],
    )

    op.create_table(
        "asset_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "asset_id",
            sa.String(36),
            sa.ForeignKey("assets.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("previous_revision", sa.Integer(), nullable=False),
        sa.Column("new_revision", sa.Integer(), nullable=False),
        sa.Column("effective_at", sa.Date()),
        sa.Column("previous_values", sa.JSON(), nullable=False),
        sa.Column("new_values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("previous_revision >= 1", name="ck_asset_events_previous_revision"),
        sa.CheckConstraint(
            "new_revision = previous_revision + 1", name="ck_asset_events_new_revision"
        ),
    )
    op.create_index(
        "ix_asset_events_asset_id_created_at",
        "asset_events",
        ["asset_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_asset_events_asset_id_created_at", table_name="asset_events")
    op.drop_table("asset_events")
    op.drop_index("ix_asset_valuations_asset_id_valued_at", table_name="asset_valuations")
    op.drop_table("asset_valuations")
    op.drop_index("ix_assets_is_active", table_name="assets")
    op.drop_index("ix_assets_asset_type", table_name="assets")
    op.drop_table("assets")
