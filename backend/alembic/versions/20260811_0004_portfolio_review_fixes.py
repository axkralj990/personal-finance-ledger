"""Add portfolio provenance, precision, and replay constraints.

Revision ID: 20260811_0004
Revises: 20260811_0003
"""

from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal

import sqlalchemy as sa
from alembic import op

revision: str = "20260811_0004"
down_revision: str | None = "20260811_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SAFE_INTEGER = 9_007_199_254_740_991


def upgrade() -> None:
    with op.batch_alter_table("assets") as batch:
        batch.add_column(sa.Column("cost_basis_fx_source", sa.String(20)))
        batch.add_column(sa.Column("cost_basis_fx_rate_to_eur", sa.String(80)))
        batch.add_column(sa.Column("cost_basis_fx_rate_date", sa.Date()))
        batch.add_column(sa.Column("archived_on", sa.Date()))
    _backfill_asset_cost_provenance()
    op.execute(
        sa.text("UPDATE assets SET archived_on = date(archived_at) WHERE archived_at IS NOT NULL")
    )
    with op.batch_alter_table("assets") as batch:
        batch.drop_constraint("ck_assets_cost_basis", type_="check")
        batch.drop_constraint("ck_assets_archive_state", type_="check")
        batch.create_check_constraint("ck_assets_cost_basis", _paired_cost_check())
        batch.create_check_constraint(
            "ck_assets_archive_state",
            "(is_active = 1 AND archived_at IS NULL AND archived_on IS NULL) OR "
            "(is_active = 0 AND archived_at IS NOT NULL AND archived_on IS NOT NULL)",
        )

    with op.batch_alter_table("asset_valuations") as batch:
        batch.add_column(sa.Column("cost_basis_fx_source", sa.String(20)))
        batch.add_column(sa.Column("cost_basis_fx_rate_to_eur", sa.String(80)))
        batch.add_column(sa.Column("cost_basis_fx_rate_date", sa.Date()))
    _backfill_valuation_cost_provenance()
    with op.batch_alter_table("asset_valuations") as batch:
        batch.drop_constraint("ck_asset_valuations_native_value", type_="check")
        batch.drop_constraint("ck_asset_valuations_eur_value", type_="check")
        batch.drop_constraint("ck_asset_valuations_cost_basis", type_="check")
        batch.create_check_constraint(
            "ck_asset_valuations_native_value",
            f"native_value_minor BETWEEN 0 AND {SAFE_INTEGER}",
        )
        batch.create_check_constraint(
            "ck_asset_valuations_eur_value",
            f"eur_value_minor BETWEEN 0 AND {SAFE_INTEGER}",
        )
        batch.create_check_constraint("ck_asset_valuations_cost_basis", _paired_cost_check())
        batch.create_unique_constraint(
            "uq_asset_valuation_quote_replay",
            ["asset_id", "source", "quote_fetched_at"],
        )


def downgrade() -> None:
    with op.batch_alter_table("asset_valuations") as batch:
        batch.drop_constraint("uq_asset_valuation_quote_replay", type_="unique")
        batch.drop_constraint("ck_asset_valuations_native_value", type_="check")
        batch.drop_constraint("ck_asset_valuations_eur_value", type_="check")
        batch.drop_constraint("ck_asset_valuations_cost_basis", type_="check")
        batch.create_check_constraint("ck_asset_valuations_native_value", "native_value_minor >= 0")
        batch.create_check_constraint("ck_asset_valuations_eur_value", "eur_value_minor >= 0")
        batch.create_check_constraint(
            "ck_asset_valuations_cost_basis",
            "(cost_basis_native_minor IS NULL AND cost_basis_eur_minor IS NULL) OR "
            "(cost_basis_native_minor >= 0 AND cost_basis_eur_minor >= 0)",
        )
        batch.drop_column("cost_basis_fx_rate_date")
        batch.drop_column("cost_basis_fx_rate_to_eur")
        batch.drop_column("cost_basis_fx_source")

    with op.batch_alter_table("assets") as batch:
        batch.drop_constraint("ck_assets_cost_basis", type_="check")
        batch.drop_constraint("ck_assets_archive_state", type_="check")
        batch.create_check_constraint(
            "ck_assets_cost_basis",
            "(cost_basis_native_minor IS NULL AND cost_basis_eur_minor IS NULL) OR "
            "(cost_basis_native_minor >= 0 AND cost_basis_eur_minor >= 0)",
        )
        batch.create_check_constraint(
            "ck_assets_archive_state",
            "(is_active = 1 AND archived_at IS NULL) OR "
            "(is_active = 0 AND archived_at IS NOT NULL)",
        )
        batch.drop_column("archived_on")
        batch.drop_column("cost_basis_fx_rate_date")
        batch.drop_column("cost_basis_fx_rate_to_eur")
        batch.drop_column("cost_basis_fx_source")


def _paired_cost_check() -> str:
    return (
        "(cost_basis_native_minor IS NULL AND cost_basis_eur_minor IS NULL AND "
        "cost_basis_fx_source IS NULL AND cost_basis_fx_rate_to_eur IS NULL AND "
        "cost_basis_fx_rate_date IS NULL) OR "
        "(cost_basis_native_minor IS NOT NULL AND cost_basis_eur_minor IS NOT NULL AND "
        "cost_basis_fx_source IS NOT NULL AND cost_basis_fx_rate_to_eur IS NOT NULL AND "
        "cost_basis_fx_rate_date IS NOT NULL AND cost_basis_native_minor >= 0 AND "
        f"cost_basis_eur_minor >= 0 AND cost_basis_native_minor <= {SAFE_INTEGER} AND "
        f"cost_basis_eur_minor <= {SAFE_INTEGER})"
    )


def _backfill_asset_cost_provenance() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE assets SET cost_basis_native_minor = NULL, cost_basis_eur_minor = NULL "
            "WHERE (cost_basis_native_minor IS NULL) != (cost_basis_eur_minor IS NULL) "
            "OR (cost_basis_native_minor = 0 AND cost_basis_eur_minor != 0) "
            "OR (currency = 'EUR' AND cost_basis_native_minor != cost_basis_eur_minor)"
        )
    )
    rows = list(
        connection.execute(
            sa.text(
                "SELECT id, currency, acquisition_date, cost_basis_native_minor, "
                "cost_basis_eur_minor FROM assets WHERE cost_basis_native_minor IS NOT NULL"
            )
        ).mappings()
    )
    for row in rows:
        source = "IDENTITY" if row["currency"] == "EUR" else "MANUAL"
        rate = _backfill_rate(row["cost_basis_native_minor"], row["cost_basis_eur_minor"])
        connection.execute(
            sa.text(
                "UPDATE assets SET cost_basis_fx_source = :source, "
                "cost_basis_fx_rate_to_eur = :rate, cost_basis_fx_rate_date = :rate_date "
                "WHERE id = :id"
            ),
            {
                "id": row["id"],
                "source": source,
                "rate": "1" if source == "IDENTITY" else rate,
                "rate_date": row["acquisition_date"],
            },
        )


def _backfill_valuation_cost_provenance() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE asset_valuations SET cost_basis_native_minor = NULL, "
            "cost_basis_eur_minor = NULL WHERE "
            "(cost_basis_native_minor IS NULL) != (cost_basis_eur_minor IS NULL) "
            "OR (cost_basis_native_minor = 0 AND cost_basis_eur_minor != 0) "
            "OR ((SELECT currency FROM assets WHERE assets.id = asset_valuations.asset_id) = "
            "'EUR' AND cost_basis_native_minor != cost_basis_eur_minor)"
        )
    )
    rows = list(
        connection.execute(
            sa.text(
                "SELECT asset_valuations.id, assets.currency, assets.acquisition_date, "
                "asset_valuations.cost_basis_native_minor, "
                "asset_valuations.cost_basis_eur_minor FROM asset_valuations "
                "JOIN assets ON assets.id = asset_valuations.asset_id "
                "WHERE asset_valuations.cost_basis_native_minor IS NOT NULL"
            )
        ).mappings()
    )
    for row in rows:
        source = "IDENTITY" if row["currency"] == "EUR" else "MANUAL"
        rate = _backfill_rate(row["cost_basis_native_minor"], row["cost_basis_eur_minor"])
        connection.execute(
            sa.text(
                "UPDATE asset_valuations SET cost_basis_fx_source = :source, "
                "cost_basis_fx_rate_to_eur = :rate, cost_basis_fx_rate_date = :rate_date "
                "WHERE id = :id"
            ),
            {
                "id": row["id"],
                "source": source,
                "rate": "1" if source == "IDENTITY" else rate,
                "rate_date": row["acquisition_date"],
            },
        )


def _backfill_rate(native_minor: int, eur_minor: int) -> str:
    if native_minor == 0:
        return "1"
    rate = (Decimal(eur_minor) / Decimal(native_minor)).quantize(
        Decimal("0.000000000000000001"), rounding=ROUND_HALF_UP
    )
    if rate == 0:
        rate = Decimal("0.000000000000000001")
    rendered = format(rate, "f")
    return rendered.rstrip("0").rstrip(".") or "0"
