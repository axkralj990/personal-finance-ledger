from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select, text
from sqlalchemy.exc import IntegrityError

from backend.app.api.assets import _archive_date
from backend.app.config import Settings
from backend.app.database.models import (
    Asset,
    AssetEvent,
    AssetType,
    AssetValuation,
    QuoteInterval,
    ValuationSource,
)
from backend.app.portfolio.domain import FxPreviewData, QuoteSnapshotData
from backend.app.portfolio.market_data import MarketDataClient, MarketDataError
from backend.app.portfolio.precision import JS_SAFE_INTEGER


def test_portfolio_migration_adds_only_three_new_tables(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite3'}")
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260810_0002")
    before = set(inspect(engine).get_table_names())

    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "20260811_0003")
        connection.exec_driver_sql(
            """
            INSERT INTO assets (
                id, name, asset_type, currency, acquisition_date, quantity,
                cost_basis_native_minor, cost_basis_eur_minor, quote_symbol,
                quote_exchange, quote_mic_code, is_active, revision, created_at,
                updated_at, archived_at
            ) VALUES (
                'migrated-asset', 'Migrated', 'OTHER', 'USD', '2026-01-01', NULL,
                300, 240, NULL, NULL, NULL, 1, 1, '2026-01-01', '2026-01-01', NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO assets (
                id, name, asset_type, currency, acquisition_date, quantity,
                cost_basis_native_minor, cost_basis_eur_minor, quote_symbol,
                quote_exchange, quote_mic_code, is_active, revision, created_at,
                updated_at, archived_at
            ) VALUES (
                'migrated-archive', 'Archived', 'BANK_CASH', 'EUR', '2026-01-01',
                NULL, NULL, NULL, NULL, NULL, NULL, 0, 2, '2026-01-01',
                '2026-03-31', '2026-03-31 23:30:00'
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO asset_valuations (
                id, asset_id, valued_at, native_value_minor, eur_value_minor,
                quantity, unit_price, cost_basis_native_minor, cost_basis_eur_minor,
                source, quote_symbol, quote_exchange, quote_mic_code, quote_name,
                quote_fetched_at, fx_source, fx_rate_to_eur, fx_rate_date, created_at
            ) VALUES (
                'migrated-value', 'migrated-asset', '2026-01-01', 300, 240,
                NULL, NULL, 300, 240, 'MANUAL', NULL, NULL, NULL, NULL, NULL,
                'MANUAL', '0.8', '2026-01-01', '2026-01-01'
            )
            """
        )
    with engine.begin() as connection:
        config.attributes["connection"] = connection
        command.upgrade(config, "head")

    inspector = inspect(engine)
    after = set(inspector.get_table_names())
    assert {"assets", "asset_valuations", "asset_events"} <= after - before
    assert {index["name"] for index in inspector.get_indexes("asset_valuations")} == {
        "ix_asset_valuations_asset_id_valued_at",
        "uq_asset_valuation_monthly",
    }
    assert {item["name"] for item in inspector.get_unique_constraints("asset_valuations")} == {
        "uq_asset_valuation_quote_replay"
    }
    quote_replay = next(
        item
        for item in inspector.get_unique_constraints("asset_valuations")
        if item["name"] == "uq_asset_valuation_quote_replay"
    )
    assert quote_replay["column_names"] == [
        "asset_id",
        "source",
        "quote_fetched_at",
        "valued_at",
    ]
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO asset_valuations (
                id, asset_id, valued_at, native_value_minor, eur_value_minor,
                quantity, unit_price, cost_basis_native_minor, cost_basis_eur_minor,
                cost_basis_fx_source, cost_basis_fx_rate_to_eur, cost_basis_fx_rate_date,
                source, quote_symbol, quote_exchange, quote_mic_code, quote_name,
                quote_fetched_at, quote_interval, fx_source, fx_rate_to_eur, fx_rate_date,
                created_at
            ) VALUES (
                'yahoo-value', 'migrated-asset', '2026-08-11', 400, 320,
                NULL, '4', 300, 240, 'MANUAL', '0.8', '2026-01-01',
                'YAHOO_FINANCE', 'CSPX', 'LSE', NULL, 'CSPX ETF',
                '2026-08-11 12:00:00', 'LIVE', 'ECB', '0.8', '2026-08-11',
                '2026-08-11'
            )
            """
        )
    assert all(
        "FLOAT" not in str(column["type"]).upper()
        for table in ("assets", "asset_valuations", "asset_events")
        for column in inspector.get_columns(table)
    )
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == (
            "20260814_0009"
        )
        provenance = connection.exec_driver_sql(
            "SELECT cost_basis_fx_source, cost_basis_fx_rate_to_eur "
            "FROM asset_valuations WHERE id = 'migrated-value'"
        ).one()
        assert provenance == ("MANUAL", "0.8")
        archived_on = connection.exec_driver_sql(
            "SELECT archived_on FROM assets WHERE id = 'migrated-archive'"
        ).scalar()
        assert archived_on == "2026-03-31"
    engine.dispose()


def test_database_rejects_unpaired_asset_and_valuation_cost_basis(database) -> None:
    now = datetime.now(UTC).isoformat()
    with database.engine.connect() as connection:
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO assets (
                        id, name, asset_type, currency, acquisition_date, quantity,
                        cost_basis_native_minor, cost_basis_eur_minor,
                        cost_basis_fx_source, cost_basis_fx_rate_to_eur,
                        cost_basis_fx_rate_date, quote_symbol, quote_exchange,
                        quote_mic_code, is_active, revision, created_at, updated_at,
                        archived_at
                    ) VALUES (
                        'bad-pair', 'Bad pair', 'OTHER', 'EUR', '2026-01-01', NULL,
                        NULL, 100, 'IDENTITY', '1', '2026-01-01', NULL, NULL,
                        NULL, 1, 1, :now, :now, NULL
                    )
                    """
                ),
                {"now": now},
            )
        connection.rollback()

        connection.execute(
            text(
                """
                INSERT INTO assets (
                    id, name, asset_type, currency, acquisition_date, quantity,
                    cost_basis_native_minor, cost_basis_eur_minor,
                    cost_basis_fx_source, cost_basis_fx_rate_to_eur,
                    cost_basis_fx_rate_date, quote_symbol, quote_exchange,
                    quote_mic_code, is_active, revision, created_at, updated_at,
                    archived_at
                ) VALUES (
                    'valid-asset', 'Valid', 'OTHER', 'EUR', '2026-01-01', NULL,
                    NULL, NULL, NULL, NULL, NULL, NULL, NULL, NULL,
                    1, 1, :now, :now, NULL
                )
                """
            ),
            {"now": now},
        )
        connection.commit()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """
                    INSERT INTO asset_valuations (
                        id, asset_id, valued_at, native_value_minor, eur_value_minor,
                        quantity, unit_price, cost_basis_native_minor,
                        cost_basis_eur_minor, cost_basis_fx_source,
                        cost_basis_fx_rate_to_eur, cost_basis_fx_rate_date, source,
                        quote_symbol, quote_exchange, quote_mic_code, quote_name,
                        quote_fetched_at, fx_source, fx_rate_to_eur, fx_rate_date,
                        created_at
                    ) VALUES (
                        'bad-valuation', 'valid-asset', '2026-01-01', 100, 100,
                        NULL, NULL, NULL, 100, 'IDENTITY', '1', '2026-01-01',
                        'MANUAL', NULL, NULL, NULL, NULL, NULL, 'IDENTITY', '1',
                        '2026-01-01', :now
                    )
                    """
                ),
                {"now": now},
            )
        connection.rollback()


def test_asset_lifecycle_revision_audit_backdated_values_and_archive(
    app, client: TestClient
) -> None:
    payload = _stock_payload()
    payload["asset_type"] = "OTHER"
    payload["quote"] = None
    created_response = client.post("/api/v1/assets", json=payload)
    assert created_response.status_code == 201
    created = created_response.json()
    asset_id = created["id"]
    assert created["revision"] == 1
    assert created["latest_valuation"]["eur_value_minor"] == 240
    assert created["latest_valuation"]["fx_rate_to_eur"] == "0.8"
    assert created["cost_basis_fx_source"] == "MANUAL"
    assert created["latest_valuation"]["cost_basis_fx_rate_to_eur"] == "0.8"

    correction = client.patch(
        f"/api/v1/assets/{asset_id}",
        json={"expected_revision": 1, "name": "Acme renamed"},
    )
    assert correction.status_code == 200
    assert correction.json()["revision"] == 2

    stale = client.patch(
        f"/api/v1/assets/{asset_id}",
        json={"expected_revision": 1, "name": "Stale"},
    )
    assert stale.status_code == 409
    assert stale.json()["details"] == {"current_revision": 2}

    missing_replacement = client.patch(
        f"/api/v1/assets/{asset_id}",
        json={"expected_revision": 2, "quantity": "4"},
    )
    assert missing_replacement.status_code == 422
    assert missing_replacement.json()["code"] == "replacement_valuation_required"

    position = client.patch(
        f"/api/v1/assets/{asset_id}",
        json={
            "expected_revision": 2,
            "quantity": "4",
            "effective_at": "2026-08-01",
            "replacement_valuation": {
                "valued_at": "2026-08-01",
                "native_value_minor": 402,
                "unit_price": "1.005",
                "fx_source": "MANUAL",
                "fx_rate_to_eur": "0.8",
                "fx_rate_date": "2026-08-01",
            },
        },
    )
    assert position.status_code == 200
    assert position.json()["revision"] == 3
    assert position.json()["latest_valuation"]["native_value_minor"] == 402
    assert position.json()["latest_valuation"]["eur_value_minor"] == 322
    historical = client.get("/api/v1/portfolio", params={"as_of": "2026-07-31"}).json()
    assert historical["holdings"][0]["quantity"] == "3"

    backdated = client.post(
        f"/api/v1/assets/{asset_id}/valuations",
        json={
            "expected_revision": 3,
            "valued_at": "2026-07-31",
            "native_value_minor": 300,
            "unit_price": "1",
            "fx_source": "MANUAL",
            "fx_rate_to_eur": "0.8",
            "fx_rate_date": "2026-07-31",
        },
    )
    assert backdated.status_code == 201
    valuations = client.get(f"/api/v1/assets/{asset_id}/valuations").json()
    assert [item["valued_at"] for item in valuations] == [
        "2026-08-01",
        "2026-07-31",
        "2026-07-01",
    ]
    assert valuations[1]["quantity"] == "3"
    assert all(item["source"] == "MANUAL" for item in valuations)

    archived = client.patch(
        f"/api/v1/assets/{asset_id}",
        json={"expected_revision": 3, "is_active": False},
    )
    assert archived.status_code == 200
    assert archived.json()["revision"] == 4
    assert archived.json()["is_active"] is False
    assert client.get("/api/v1/assets").json() == []
    assert (
        client.get("/api/v1/assets", params={"include_archived": True}).json()[0]["id"] == asset_id
    )
    rejected = client.post(
        f"/api/v1/assets/{asset_id}/valuations",
        json={"expected_revision": 4, "valued_at": "2026-08-02", "native_value_minor": 1},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "asset_archived"

    with app.state.database.session() as session:
        events = list(
            session.scalars(
                select(AssetEvent)
                .where(AssetEvent.asset_id == asset_id)
                .order_by(AssetEvent.previous_revision)
            )
        )
        revisions = [
            (event.event_type, event.previous_revision, event.new_revision) for event in events
        ]
        assert revisions == [
            ("CORRECTION", 1, 2),
            ("CORRECTION", 2, 3),
            ("ARCHIVED", 3, 4),
        ]
        assert events[1].previous_values["quantity"] == "3"
        assert events[1].new_values["quantity"] == "4"
        assert events[2].new_values["archived_on"] == archived.json()["archived_on"]


def test_asset_create_is_idempotent_for_client_generated_id(app, client: TestClient) -> None:
    payload = _stock_payload(name="Idempotent", symbol="IDEM")
    payload["id"] = "fdcc7838-bd95-49d5-9874-d252e68fc4a1"

    first = client.post("/api/v1/assets", json=payload)
    second = client.post("/api/v1/assets", json=payload)

    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["id"] == second.json()["id"] == payload["id"]
    with app.state.database.session() as session:
        assert session.scalar(select(func.count(Asset.id))) == 1

    mismatched = dict(payload)
    mismatched["name"] = "Different purchase"
    conflict = client.post("/api/v1/assets", json=mismatched)
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "asset_id_reused"


def test_canonical_decimal_and_manual_fx_validation(client: TestClient) -> None:
    noncanonical = _stock_payload()
    noncanonical["quantity"] = "3.0"
    response = client.post("/api/v1/assets", json=noncanonical)
    assert response.status_code == 422
    assert response.json()["field"] == "quantity"

    missing_fx = _stock_payload()
    missing_fx["initial_valuation"] = {
        "valued_at": "2026-07-01",
        "native_value_minor": 300,
        "unit_price": "1",
    }
    response = client.post("/api/v1/assets", json=missing_fx)
    assert response.status_code == 422
    assert response.json()["code"] == "manual_fx_required"

    mismatch = _stock_payload()
    mismatch["initial_valuation"]["native_value_minor"] = 301
    response = client.post("/api/v1/assets", json=mismatch)
    assert response.status_code == 422
    assert response.json()["code"] == "valuation_mismatch"


def test_acquisition_date_is_immutable_and_patch_nulls_are_rejected(
    client: TestClient,
) -> None:
    asset = _create_stock(client)
    acquisition = client.patch(
        f"/api/v1/assets/{asset['id']}",
        json={"expected_revision": 1, "acquisition_date": "2025-01-01"},
    )
    assert acquisition.status_code == 422
    assert acquisition.json()["field"] == "acquisition_date"

    for field in ("name", "asset_type", "is_active"):
        response = client.patch(
            f"/api/v1/assets/{asset['id']}",
            json={"expected_revision": 1, field: None},
        )
        assert response.status_code == 422

    asset_type = client.patch(
        f"/api/v1/assets/{asset['id']}",
        json={"expected_revision": 1, "asset_type": "BANK_CASH"},
    )
    assert asset_type.status_code == 422
    assert asset_type.json()["code"] == "immutable_asset_type"

    purchase = client.patch(
        f"/api/v1/assets/{asset['id']}",
        json={
            "expected_revision": 1,
            "quantity": "4",
            "effective_at": "2026-08-01",
            "replacement_valuation": {
                "valued_at": "2026-08-01",
                "native_value_minor": 400,
                "unit_price": "1",
                "fx_source": "MANUAL",
                "fx_rate_to_eur": "0.8",
                "fx_rate_date": "2026-08-01",
            },
        },
    )
    assert purchase.status_code == 422
    assert purchase.json()["code"] == "immutable_security_purchase"


def test_archived_assets_remain_in_prior_current_and_history_reports(
    client: TestClient,
) -> None:
    acquisition_date = date.today() - timedelta(days=75)
    created = client.post(
        "/api/v1/assets",
        json={
            "name": "Archived savings",
            "asset_type": "BANK_CASH",
            "currency": "EUR",
            "acquisition_date": acquisition_date.isoformat(),
            "initial_valuation": {
                "valued_at": acquisition_date.isoformat(),
                "native_value_minor": 12345,
            },
        },
    ).json()
    archived_response = client.patch(
        f"/api/v1/assets/{created['id']}",
        json={"expected_revision": 1, "is_active": False},
    )
    assert archived_response.status_code == 200
    archive_date = datetime.fromisoformat(
        archived_response.json()["archived_at"].replace("Z", "+00:00")
    ).date()

    prior = client.get(
        "/api/v1/portfolio", params={"as_of": (archive_date - timedelta(days=1)).isoformat()}
    ).json()
    assert prior["asset_count"] == 1
    assert prior["total_value_minor"] == 12345
    assert prior["holdings"][0]["asset_id"] == created["id"]

    archived_day = client.get(
        "/api/v1/portfolio", params={"as_of": archive_date.isoformat()}
    ).json()
    assert archived_day["asset_count"] == 0
    assert archived_day["holdings"] == []

    later = client.get(
        "/api/v1/portfolio", params={"as_of": (archive_date + timedelta(days=40)).isoformat()}
    ).json()
    prior_month_ends = [
        point for point in later["history"] if date.fromisoformat(point["date"]) < archive_date
    ]
    assert prior_month_ends
    assert all(point["total_value_minor"] == 12345 for point in prior_month_ends)
    assert all(
        point["known_value_minor"] == 0
        for point in later["history"]
        if date.fromisoformat(point["date"]) >= archive_date
    )


def test_archive_allows_unchanged_legacy_cost_fx_after_acquisition(app, client: TestClient) -> None:
    asset = _create_stock(client, name="Legacy FX", symbol="LEGACY")
    with app.state.database.session() as session:
        stored = session.get(Asset, asset["id"])
        assert stored is not None
        stored.cost_basis_fx_rate_date = date(2026, 8, 10)
        session.commit()

    archived = client.patch(
        f"/api/v1/assets/{asset['id']}",
        json={"expected_revision": 1, "is_active": False},
    )

    assert archived.status_code == 200
    assert archived.json()["is_active"] is False
    assert archived.json()["cost_basis_fx_rate_date"] == "2026-08-10"


def test_cost_basis_fx_provenance_create_patch_and_snapshot(app, client: TestClient) -> None:
    eur_payload = {
        "name": "EUR property",
        "asset_type": "FIXED_ASSET",
        "currency": "EUR",
        "acquisition_date": "2026-01-01",
        "cost_basis_native_minor": 10000,
        "cost_basis_eur_minor": 10000,
        "cost_basis_fx_source": "IDENTITY",
        "cost_basis_fx_rate_to_eur": "1",
        "cost_basis_fx_rate_date": "2026-01-01",
        "initial_valuation": {"valued_at": "2026-01-01", "native_value_minor": 11000},
    }
    created = client.post("/api/v1/assets", json=eur_payload)
    assert created.status_code == 201
    assert created.json()["cost_basis_fx_source"] == "IDENTITY"
    assert created.json()["latest_valuation"]["cost_basis_fx_rate_to_eur"] == "1"

    invalid_eur = dict(eur_payload)
    invalid_eur["name"] = "Invalid EUR"
    invalid_eur["cost_basis_eur_minor"] = 9999
    response = client.post("/api/v1/assets", json=invalid_eur)
    assert response.status_code == 422
    assert response.json()["code"] == "invalid_eur_cost_basis"

    invalid_non_eur = _stock_payload(name="Bad cost", symbol="BAD")
    invalid_non_eur["cost_basis_eur_minor"] = 241
    response = client.post("/api/v1/assets", json=invalid_non_eur)
    assert response.status_code == 422
    assert response.json()["code"] == "cost_basis_fx_mismatch"

    other_payload = _stock_payload(name="Updated cost", symbol="COST")
    other_payload["asset_type"] = "OTHER"
    other_payload["quote"] = None
    stock_response = client.post("/api/v1/assets", json=other_payload)
    assert stock_response.status_code == 201
    stock = stock_response.json()
    app.state.market_data_client_factory = _StubMarketDataClient
    fx_preview = client.get(
        "/api/v1/portfolio/fx-preview",
        params={"currency": "USD", "valued_at": "2026-08-01"},
    ).json()
    patched = client.patch(
        f"/api/v1/assets/{stock['id']}",
        json={
            "expected_revision": 1,
            "cost_basis_native_minor": 400,
            "cost_basis_eur_minor": 320,
            "cost_basis_fx_source": "ECB",
            "cost_basis_fx_rate_to_eur": fx_preview["rate_to_eur"],
            "cost_basis_fx_rate_date": fx_preview["rate_date"],
            "cost_basis_fx_preview_token": fx_preview["preview_token"],
            "effective_at": "2026-08-01",
            "replacement_valuation": {
                "valued_at": "2026-08-01",
                "native_value_minor": 300,
                "unit_price": "1",
                "fx_source": "ECB",
                "fx_rate_to_eur": fx_preview["rate_to_eur"],
                "fx_rate_date": fx_preview["rate_date"],
                "fx_preview_token": fx_preview["preview_token"],
            },
        },
    )
    assert patched.status_code == 200
    assert patched.json()["cost_basis_fx_source"] == "ECB"
    assert patched.json()["latest_valuation"]["cost_basis_fx_source"] == "ECB"
    assert patched.json()["latest_valuation"]["fx_source"] == "ECB"
    with app.state.database.session() as session:
        event = session.scalar(select(AssetEvent).where(AssetEvent.asset_id == stock["id"]))
        assert event.new_values["cost_basis_fx_source"] == "ECB"

    backdated = client.post(
        f"/api/v1/assets/{stock['id']}/valuations",
        json={
            "expected_revision": 2,
            "valued_at": "2026-07-31",
            "native_value_minor": 300,
            "unit_price": "1",
            "fx_source": "MANUAL",
            "fx_rate_to_eur": "0.8",
            "fx_rate_date": "2026-07-31",
        },
    )
    assert backdated.status_code == 201
    assert backdated.json()["cost_basis_fx_rate_date"] == "2026-07-01"


@pytest.mark.parametrize("currency", ["JPY", "KWD"])
def test_portfolio_rejects_non_two_decimal_currencies(client: TestClient, currency: str) -> None:
    payload = _stock_payload()
    payload["currency"] = currency
    response = client.post("/api/v1/assets", json=payload)
    assert response.status_code == 422
    assert response.json()["code"] == "unsupported_portfolio_currency"


def test_portfolio_precision_bounds(client: TestClient) -> None:
    money = _stock_payload()
    money["initial_valuation"]["native_value_minor"] = JS_SAFE_INTEGER + 1
    assert client.post("/api/v1/assets", json=money).status_code == 422

    decimal_scale = _stock_payload()
    decimal_scale["quantity"] = "1.1234567890123456789"
    assert client.post("/api/v1/assets", json=decimal_scale).status_code == 422

    overflow = {
        "name": "Overflow",
        "asset_type": "OTHER",
        "currency": "EUR",
        "acquisition_date": "2026-01-01",
        "quantity": "999999999999999",
        "initial_valuation": {
            "valued_at": "2026-01-01",
            "native_value_minor": 0,
            "unit_price": "999999999999999",
        },
    }
    response = client.post("/api/v1/assets", json=overflow)
    assert response.status_code == 422
    assert response.json()["code"] == "portfolio_arithmetic_overflow"

    for name in ("Large one", "Large two"):
        response = client.post(
            "/api/v1/assets",
            json={
                "name": name,
                "asset_type": "BANK_CASH",
                "currency": "EUR",
                "acquisition_date": "2026-01-01",
                "initial_valuation": {
                    "valued_at": "2026-01-01",
                    "native_value_minor": JS_SAFE_INTEGER,
                },
            },
        )
        assert response.status_code == 201
    aggregate = client.get("/api/v1/portfolio", params={"as_of": "2026-01-31"})
    assert aggregate.status_code == 422
    assert aggregate.json()["code"] == "portfolio_arithmetic_overflow"


def test_portfolio_aggregate_completeness_pnl_allocation_and_history(
    client: TestClient,
) -> None:
    cash = client.post(
        "/api/v1/assets",
        json={
            "name": "Savings",
            "asset_type": "BANK_CASH",
            "currency": "EUR",
            "acquisition_date": "2026-06-01",
            "initial_valuation": {
                "valued_at": "2026-06-15",
                "native_value_minor": 10000,
            },
        },
    )
    assert cash.status_code == 201
    stock = _create_stock(client)
    stock_id = stock["id"]
    updated = client.post(
        f"/api/v1/assets/{stock_id}/valuations",
        json={
            "expected_revision": 1,
            "valued_at": "2026-07-20",
            "native_value_minor": 450,
            "unit_price": "1.5",
            "fx_source": "MANUAL",
            "fx_rate_to_eur": "0.8",
            "fx_rate_date": "2026-07-18",
        },
    )
    assert updated.status_code == 201

    report = client.get("/api/v1/portfolio", params={"as_of": "2026-07-31"}).json()
    assert report["complete"] is True
    assert report["known_value_minor"] == 10360
    assert report["total_value_minor"] == 10360
    assert report["tracked_cost_basis_minor"] == 240
    assert report["unrealized_pnl_minor"] == 120
    assert report["return_percent"] == "50"
    assert report["pnl_eligible_assets"] == 1
    assert report["pnl_covered_assets"] == 1
    assert len(report["pnl_by_asset"]) == 1
    cash_holding = next(item for item in report["holdings"] if item["name"] == "Savings")
    assert cash_holding["unrealized_pnl_minor"] is None
    assert sum(item["value_minor"] for item in report["allocation_by_type"]) == 10360
    assert [(item["date"], item["total_value_minor"]) for item in report["history"]] == [
        ("2026-06-30", 10000),
        ("2026-07-31", 10360),
    ]

    incomplete = client.get("/api/v1/portfolio", params={"as_of": "2026-07-10"}).json()
    assert incomplete["complete"] is True
    assert incomplete["total_value_minor"] == 10240

    future_initial = _stock_payload(name="Late priced", symbol="LATE")
    future_initial["acquisition_date"] = "2026-07-01"
    future_initial["initial_valuation"]["valued_at"] = "2026-08-01"
    late = client.post("/api/v1/assets", json=future_initial).json()
    incomplete = client.get("/api/v1/portfolio", params={"as_of": "2026-07-31"}).json()
    assert incomplete["complete"] is False
    assert incomplete["total_value_minor"] is None
    assert incomplete["known_value_minor"] == 10360
    assert incomplete["missing_asset_ids"] == [late["id"]]


def test_pnl_coverage_counts_non_cash_assets_without_cost_basis(client: TestClient) -> None:
    response = client.post(
        "/api/v1/assets",
        json={
            "name": "Untracked property",
            "asset_type": "FIXED_ASSET",
            "currency": "EUR",
            "acquisition_date": "2026-01-01",
            "initial_valuation": {
                "valued_at": "2026-01-01",
                "native_value_minor": 50000,
            },
        },
    )
    assert response.status_code == 201

    report = client.get("/api/v1/portfolio", params={"as_of": "2026-01-31"}).json()
    assert report["pnl_eligible_assets"] == 1
    assert report["pnl_covered_assets"] == 0
    assert report["tracked_cost_basis_minor"] is None
    assert report["unrealized_pnl_minor"] is None
    assert report["pnl_by_asset"][0]["cost_basis_eur_minor"] is None
    assert report["pnl_by_asset"][0]["current_value_eur_minor"] == 50000


def test_purchase_snapshot_without_market_quote_does_not_report_zero_pnl(
    client: TestClient,
) -> None:
    stock = _create_stock(client, name="Waiting for quote", symbol="WAIT")

    report = client.get("/api/v1/portfolio", params={"as_of": "2026-07-31"}).json()
    pnl = next(item for item in report["pnl_by_asset"] if item["asset_id"] == stock["id"])
    holding = next(item for item in report["holdings"] if item["asset_id"] == stock["id"])

    assert report["pnl_covered_assets"] == 0
    assert report["unrealized_pnl_minor"] is None
    assert pnl["cost_basis_eur_minor"] == 240
    assert pnl["current_value_eur_minor"] is None
    assert pnl["unrealized_pnl_minor"] is None
    assert holding["unrealized_pnl_minor"] is None


def test_quote_preview_partial_failure_does_not_write_and_snapshot_post_is_atomic(
    app, client: TestClient
) -> None:
    first = _create_stock(client, name="Quoted one", symbol="OK1")
    second = _create_stock(client, name="Quoted two", symbol="OK2")
    broken = _create_stock(client, name="Broken", symbol="FAIL")
    app.state.market_data_client_factory = _StubMarketDataClient

    with app.state.database.session() as session:
        before = session.scalar(select(func.count(AssetValuation.id)))
    preview_response = client.get(
        "/api/v1/portfolio/quote-preview",
        params=[
            ("asset_id", first["id"]),
            ("asset_id", second["id"]),
            ("asset_id", broken["id"]),
        ],
    )
    assert preview_response.status_code == 200
    preview = preview_response.json()["items"]
    assert preview[0]["status"] == "ready"
    assert preview[0]["source"] == "TWELVE_DATA"
    assert len(preview[0]["preview_token"]) == 64
    assert preview[2] == {
        "status": "error",
        "asset_id": broken["id"],
        "asset_revision": 1,
        "error": {
            "code": "quote_unavailable",
            "message": "Synthetic quote failure",
            "recoverable": True,
        },
    }
    with app.state.database.session() as session:
        assert session.scalar(select(func.count(AssetValuation.id))) == before

    changed = client.patch(
        f"/api/v1/assets/{second['id']}",
        json={"expected_revision": 1, "name": "Changed after preview"},
    )
    assert changed.status_code == 200
    atomic_failure = client.post(
        "/api/v1/portfolio/quote-snapshots",
        json={"items": preview[:2]},
    )
    assert atomic_failure.status_code == 409
    assert atomic_failure.json()["code"] == "revision_conflict"
    with app.state.database.session() as session:
        assert session.scalar(select(func.count(AssetValuation.id))) == before

    forged = dict(preview[0])
    forged["preview_token"] = "0" * 64
    forged_response = client.post("/api/v1/portfolio/quote-snapshots", json={"items": [forged]})
    assert forged_response.status_code == 409
    assert forged_response.json()["code"] == "invalid_preview_token"

    persisted = client.post(
        "/api/v1/portfolio/quote-snapshots",
        json={"items": [preview[0]]},
    )
    assert persisted.status_code == 201
    valuation = persisted.json()["items"][0]
    assert valuation["source"] == "TWELVE_DATA"
    assert valuation["native_value_minor"] == 375
    assert valuation["eur_value_minor"] == 300
    assert valuation["fx_source"] == "ECB"
    replay = client.post("/api/v1/portfolio/quote-snapshots", json={"items": [preview[0]]})
    assert replay.status_code == 409
    assert replay.json()["code"] == "quote_preview_replayed"


def test_yahoo_preview_source_is_signed_and_persisted(app, client: TestClient) -> None:
    asset = _create_stock(client, name="Yahoo quote", symbol="YHOO")
    app.state.market_data_client_factory = _StubYahooMarketDataClient

    preview = client.get(
        "/api/v1/portfolio/quote-preview",
        params={"asset_id": asset["id"]},
    ).json()["items"][0]
    persisted = client.post(
        "/api/v1/portfolio/quote-snapshots",
        json={"items": [preview]},
    )

    assert preview["source"] == "YAHOO_FINANCE"
    assert persisted.status_code == 201
    assert persisted.json()["items"][0]["source"] == "YAHOO_FINANCE"
    history = client.get("/api/v1/portfolio", params={"as_of": "2026-08-11"}).json()["history"]
    assert history[-1]["date"] == "2026-08-11"
    assert history[-1]["total_value_minor"] == 300


def test_history_preview_persists_multiple_dates_and_skips_existing_months(
    app, client: TestClient
) -> None:
    payload = _stock_payload(name="Monthly history", symbol="MONTH")
    payload["acquisition_date"] = "2026-05-01"
    payload["cost_basis_fx_rate_date"] = "2026-05-01"
    payload["initial_valuation"]["valued_at"] = "2026-05-01"
    payload["initial_valuation"]["fx_rate_date"] = "2026-05-01"
    response = client.post("/api/v1/assets", json=payload)
    assert response.status_code == 201
    asset = response.json()
    app.state.market_data_client_factory = _StubHistoryMarketDataClient

    preview = client.get("/api/v1/portfolio/history-preview", params={"asset_id": asset["id"]})
    assert preview.status_code == 200
    body = preview.json()
    assert body["available_months"] == 2
    assert body["existing_months"] == 0
    assert [item["valued_at"] for item in body["items"]] == [
        "2026-05-31",
        "2026-06-30",
    ]

    persisted = client.post(
        "/api/v1/portfolio/quote-snapshots",
        json={"items": body["items"]},
    )
    assert persisted.status_code == 201, persisted.text
    assert len(persisted.json()["items"]) == 2

    repeated = client.get(
        "/api/v1/portfolio/history-preview", params={"asset_id": asset["id"]}
    ).json()
    assert repeated["existing_months"] == 2
    assert repeated["items"] == []


def test_yahoo_finance_returns_lse_quote_with_explicit_source(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "query1.finance.yahoo.com":
            return httpx.Response(
                200,
                json={
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "currency": "USD",
                                    "symbol": "CSPX.L",
                                    "exchangeName": "LSE",
                                    "regularMarketTime": 1786456472,
                                    "regularMarketPrice": 835.19,
                                    "exchangeTimezoneName": "Europe/London",
                                    "longName": "iShares Core S&P 500 UCITS ETF",
                                }
                            }
                        ],
                        "error": None,
                    }
                },
            )
        return httpx.Response(
            200,
            text="TIME_PERIOD,OBS_VALUE\n2026-08-10,1.25\n",
        )

    provider = MarketDataClient(settings)
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    asset = Asset(
        id="asset-id",
        name="CSPX",
        asset_type=AssetType.ETF,
        currency="USD",
        acquisition_date=date(2022, 10, 2),
        quantity="2",
        quote_symbol="CSPX",
        quote_exchange="LSEETF",
        is_active=True,
        revision=1,
    )

    preview = provider.preview(asset)
    provider.__exit__()

    assert preview.source == ValuationSource.YAHOO_FINANCE
    assert preview.valued_at == date(2026, 8, 11)
    assert preview.unit_price == "835.19"
    assert preview.native_value_minor == 167038
    assert preview.eur_value_minor == 133630
    assert any(request.url.path.endswith("/CSPX.L") for request in requests)


@pytest.mark.parametrize(
    ("exchange", "mic_code", "symbol", "currency", "yahoo_symbol", "yahoo_exchange"),
    [
        ("LSEETF", None, "CSPX", "USD", "CSPX.L", "LSE"),
        ("AEB", None, "IWDA", "EUR", "IWDA.AS", "AMS"),
        ("IBIS2", None, "VWCE", "EUR", "VWCE.DE", "GER"),
        ("LSEETF", "XLON", "ERNA", "USD", "ERNA.L", "LSE"),
        ("AEB", "XAMS", "IWDA", "EUR", "IWDA.AS", "AMS"),
        ("IBIS2", "XETR", "XEON", "EUR", "XEON.DE", "GER"),
    ],
)
def test_yahoo_quote_maps_ibkr_venues(
    tmp_path: Path,
    exchange: str,
    mic_code: str | None,
    symbol: str,
    currency: str,
    yahoo_symbol: str,
    yahoo_exchange: str,
) -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "query1.finance.yahoo.com":
            return httpx.Response(
                200,
                json={
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "currency": currency,
                                    "symbol": yahoo_symbol,
                                    "exchangeName": yahoo_exchange,
                                    "regularMarketTime": 1786456472,
                                    "regularMarketPrice": 100,
                                    "exchangeTimezoneName": "Europe/London",
                                    "longName": f"{symbol} ETF",
                                }
                            }
                        ],
                        "error": None,
                    }
                },
            )
        return httpx.Response(200, text="TIME_PERIOD,OBS_VALUE\n2026-08-10,1.25\n")

    provider = MarketDataClient(Settings(data_dir=tmp_path))
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    asset = Asset(
        id="asset-id",
        name=symbol,
        asset_type=AssetType.ETF,
        currency=currency,
        acquisition_date=date(2026, 1, 1),
        quantity="2",
        quote_symbol=symbol,
        quote_exchange=exchange,
        quote_mic_code=mic_code,
        is_active=True,
        revision=1,
    )

    preview = provider.preview(asset)
    provider.__exit__()

    assert preview.source == ValuationSource.YAHOO_FINANCE
    assert preview.native_value_minor == 20000
    assert any(request.url.path.endswith(f"/{yahoo_symbol}") for request in requests)


def test_yahoo_quote_is_fetched_once_for_multiple_lots(tmp_path: Path) -> None:
    yahoo_requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "query1.finance.yahoo.com":
            yahoo_requests.append(request)
            return httpx.Response(
                200,
                json={
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "currency": "EUR",
                                    "symbol": "VWCE.DE",
                                    "exchangeName": "GER",
                                    "regularMarketTime": 1786456472,
                                    "regularMarketPrice": 168.48,
                                    "exchangeTimezoneName": "Europe/Berlin",
                                    "longName": "Vanguard FTSE All-World UCITS ETF",
                                }
                            }
                        ],
                        "error": None,
                    }
                },
            )
        raise AssertionError(f"Unexpected request: {request.url}")

    provider = MarketDataClient(Settings(data_dir=tmp_path))
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    first = Asset(
        id="first-lot",
        name="VWCE",
        asset_type=AssetType.ETF,
        currency="EUR",
        acquisition_date=date(2022, 1, 1),
        quantity="2",
        quote_symbol="VWCE",
        quote_exchange="IBIS2",
        is_active=True,
        revision=1,
    )
    second = Asset(
        id="second-lot",
        name="VWCE",
        asset_type=AssetType.ETF,
        currency="EUR",
        acquisition_date=date(2023, 1, 1),
        quantity="3",
        quote_symbol="VWCE",
        quote_exchange="IBIS2",
        is_active=True,
        revision=1,
    )

    first_preview = provider.preview(first)
    second_preview = provider.preview(second)
    provider.__exit__()

    assert len(yahoo_requests) == 1
    assert first_preview.native_value_minor == 33696
    assert second_preview.native_value_minor == 50544


def test_yahoo_monthly_history_uses_month_ends_and_batched_ecb_rates(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "query1.finance.yahoo.com":
            return httpx.Response(
                200,
                json={
                    "chart": {
                        "result": [
                            {
                                "meta": {
                                    "currency": "USD",
                                    "symbol": "CSPX.L",
                                    "exchangeName": "LSE",
                                    "exchangeTimezoneName": "Europe/London",
                                    "longName": "CSPX ETF",
                                    "priceHint": 2,
                                },
                                "timestamp": [
                                    int(datetime(2022, 10, 1, 12, tzinfo=UTC).timestamp()),
                                    int(datetime(2022, 11, 1, 12, tzinfo=UTC).timestamp()),
                                ],
                                "indicators": {"quote": [{"close": [400.126, 420.0]}]},
                                "events": {},
                            }
                        ],
                        "error": None,
                    }
                },
            )
        return httpx.Response(
            200,
            text=("TIME_PERIOD,OBS_VALUE\n2022-10-31,1.0\n2022-11-30,2.0\n"),
        )

    provider = MarketDataClient(settings)
    provider._client.close()
    provider._client = httpx.Client(transport=httpx.MockTransport(handler))
    asset = Asset(
        id="asset-id",
        name="CSPX",
        asset_type=AssetType.ETF,
        currency="USD",
        acquisition_date=date(2022, 10, 2),
        quantity="2",
        quote_symbol="CSPX",
        quote_exchange="LSE",
        is_active=True,
        revision=1,
    )

    snapshots = provider.history(asset)
    provider.__exit__()

    assert [item.valued_at for item in snapshots] == [date(2022, 10, 31), date(2022, 11, 30)]
    assert [item.unit_price for item in snapshots] == ["400.13", "420"]
    assert [item.native_value_minor for item in snapshots] == [80026, 84000]
    assert [item.eur_value_minor for item in snapshots] == [80026, 42000]
    assert len({item.quote_fetched_at for item in snapshots}) == 1
    ecb_requests = [
        request for request in requests if request.url.host != "query1.finance.yahoo.com"
    ]
    assert len(ecb_requests) == 1
    assert ecb_requests[0].url.params["startPeriod"] == "2022-10-21"
    assert ecb_requests[0].url.params["endPeriod"] == "2022-11-30"


def test_fx_preview_is_get_only_and_does_not_write(app, client: TestClient) -> None:
    app.state.market_data_client_factory = _StubMarketDataClient
    with app.state.database.session() as session:
        before = session.scalar(select(func.count(AssetValuation.id)))

    usd = client.get(
        "/api/v1/portfolio/fx-preview",
        params={"currency": "USD", "valued_at": "2026-08-10"},
    )
    eur = client.get(
        "/api/v1/portfolio/fx-preview",
        params={"currency": "EUR", "valued_at": "2026-08-10"},
    )
    unsupported = client.get(
        "/api/v1/portfolio/fx-preview",
        params={"currency": "JPY", "valued_at": "2026-08-10"},
    )

    assert usd.json() == {
        "currency": "USD",
        "valued_at": "2026-08-10",
        "source": "ECB",
        "rate_to_eur": "0.8",
        "rate_date": "2026-08-09",
        "preview_token": usd.json()["preview_token"],
    }
    assert eur.json() == {
        "currency": "EUR",
        "valued_at": "2026-08-10",
        "source": "IDENTITY",
        "rate_to_eur": "1",
        "rate_date": "2026-08-10",
        "preview_token": eur.json()["preview_token"],
    }
    assert unsupported.status_code == 422
    with app.state.database.session() as session:
        assert session.scalar(select(func.count(AssetValuation.id))) == before
    openapi_path = client.get("/openapi.json").json()["paths"]["/api/v1/portfolio/fx-preview"]
    assert set(openapi_path) == {"get"}


def test_signed_fx_preview_is_bound_to_currency_date_and_rate(app, client: TestClient) -> None:
    app.state.market_data_client_factory = _StubMarketDataClient
    fx = client.get(
        "/api/v1/portfolio/fx-preview",
        params={"currency": "USD", "valued_at": "2026-08-10"},
    ).json()
    payload = _stock_payload(name="ECB cost", symbol="ECB")
    payload["acquisition_date"] = "2026-08-10"
    payload.update(
        {
            "cost_basis_fx_source": "ECB",
            "cost_basis_fx_rate_to_eur": fx["rate_to_eur"],
            "cost_basis_fx_rate_date": fx["rate_date"],
            "cost_basis_fx_preview_token": fx["preview_token"],
        }
    )
    payload["initial_valuation"]["valued_at"] = "2026-08-10"
    payload["initial_valuation"]["fx_rate_date"] = "2026-08-10"
    created = client.post("/api/v1/assets", json=payload)
    assert created.status_code == 201, created.text

    valuation_fx = client.get(
        "/api/v1/portfolio/fx-preview",
        params={"currency": "USD", "valued_at": "2026-08-11"},
    ).json()
    valuation_payload = {
        "expected_revision": 1,
        "valued_at": "2026-08-11",
        "native_value_minor": 330,
        "unit_price": "1.1",
        "fx_source": "ECB",
        "fx_rate_to_eur": valuation_fx["rate_to_eur"],
        "fx_rate_date": valuation_fx["rate_date"],
        "fx_preview_token": valuation_fx["preview_token"],
    }
    valuation = client.post(
        f"/api/v1/assets/{created.json()['id']}/valuations", json=valuation_payload
    )
    assert valuation.status_code == 201
    assert valuation.json()["fx_source"] == "ECB"

    wrong_date = dict(valuation_payload)
    wrong_date["valued_at"] = "2026-08-12"
    response = client.post(f"/api/v1/assets/{created.json()['id']}/valuations", json=wrong_date)
    assert response.status_code == 409
    assert response.json()["code"] == "invalid_fx_preview_token"

    wrong_rate = dict(valuation_payload)
    wrong_rate["fx_rate_to_eur"] = "0.81"
    response = client.post(f"/api/v1/assets/{created.json()['id']}/valuations", json=wrong_rate)
    assert response.status_code == 409

    wrong_currency = _stock_payload(name="Wrong currency", symbol="GBP")
    wrong_currency["currency"] = "GBP"
    wrong_currency["acquisition_date"] = "2026-08-10"
    wrong_currency.update(
        {
            "cost_basis_fx_source": "ECB",
            "cost_basis_fx_rate_to_eur": fx["rate_to_eur"],
            "cost_basis_fx_rate_date": fx["rate_date"],
            "cost_basis_fx_preview_token": fx["preview_token"],
        }
    )
    wrong_currency["initial_valuation"]["valued_at"] = "2026-08-10"
    wrong_currency["initial_valuation"]["fx_rate_date"] = "2026-08-10"
    response = client.post("/api/v1/assets", json=wrong_currency)
    assert response.status_code == 409

    manual_with_token = dict(valuation_payload)
    manual_with_token["fx_source"] = "MANUAL"
    response = client.post(
        f"/api/v1/assets/{created.json()['id']}/valuations",
        json=manual_with_token,
    )
    assert response.status_code == 422
    assert response.json()["code"] == "unexpected_fx_preview_token"


def test_quote_preview_expiry_ordering_and_equivalent_offset_replay(
    app, client: TestClient
) -> None:
    asset = _create_stock(client, name="Lifecycle", symbol="LIFE")
    now = datetime.now(UTC)
    latest_at = now - timedelta(hours=1)

    app.state.market_data_client_factory = lambda settings: _StubMarketDataClient(
        settings, fetched_at=latest_at
    )
    latest = client.get("/api/v1/portfolio/quote-preview", params={"asset_id": asset["id"]}).json()[
        "items"
    ][0]
    assert (
        client.post("/api/v1/portfolio/quote-snapshots", json={"items": [latest]}).status_code
        == 201
    )

    equivalent_offset = latest_at.astimezone(timezone(timedelta(hours=2)))
    app.state.market_data_client_factory = lambda settings: _StubMarketDataClient(
        settings, fetched_at=equivalent_offset
    )
    equivalent = client.get(
        "/api/v1/portfolio/quote-preview", params={"asset_id": asset["id"]}
    ).json()["items"][0]
    replay = client.post("/api/v1/portfolio/quote-snapshots", json={"items": [equivalent]})
    assert replay.status_code == 409
    assert replay.json()["code"] == "quote_preview_replayed"

    app.state.market_data_client_factory = lambda settings: _StubMarketDataClient(
        settings, fetched_at=latest_at - timedelta(hours=1)
    )
    older = client.get("/api/v1/portfolio/quote-preview", params={"asset_id": asset["id"]}).json()[
        "items"
    ][0]
    older_response = client.post("/api/v1/portfolio/quote-snapshots", json={"items": [older]})
    assert older_response.status_code == 409
    assert older_response.json()["code"] == "quote_snapshot_not_newer"

    expired_asset = _create_stock(client, name="Expired", symbol="OLD")
    app.state.market_data_client_factory = lambda settings: _StubMarketDataClient(
        settings, fetched_at=now - timedelta(hours=25)
    )
    expired = client.get(
        "/api/v1/portfolio/quote-preview",
        params={"asset_id": expired_asset["id"]},
    ).json()["items"][0]
    expired_response = client.post("/api/v1/portfolio/quote-snapshots", json={"items": [expired]})
    assert expired_response.status_code == 409
    assert expired_response.json()["code"] == "quote_preview_expired"


def test_ljubljana_archive_date_controls_month_boundary(
    app, client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    settings = Settings(
        data_dir=tmp_path,
        timezone="Europe/Ljubljana",
    )
    assert _archive_date(settings, datetime(2026, 3, 31, 22, 30, tzinfo=UTC)) == date(2026, 4, 1)
    monkeypatch.setattr("backend.app.api.assets._archive_date", lambda _settings: date(2026, 4, 1))
    asset = client.post(
        "/api/v1/assets",
        json={
            "name": "Month boundary",
            "asset_type": "BANK_CASH",
            "currency": "EUR",
            "acquisition_date": "2026-03-01",
            "initial_valuation": {
                "valued_at": "2026-03-01",
                "native_value_minor": 100,
            },
        },
    ).json()
    archived = client.patch(
        f"/api/v1/assets/{asset['id']}",
        json={"expected_revision": 1, "is_active": False},
    )
    assert archived.status_code == 200
    assert archived.json()["archived_on"] == "2026-04-01"
    march = client.get("/api/v1/portfolio", params={"as_of": "2026-03-31"}).json()
    april = client.get("/api/v1/portfolio", params={"as_of": "2026-04-01"}).json()
    history = client.get("/api/v1/portfolio", params={"as_of": "2026-04-30"}).json()["history"]
    assert march["asset_count"] == 1
    assert april["asset_count"] == 0
    assert [(point["date"], point["known_value_minor"]) for point in history] == [
        ("2026-03-31", 100),
        ("2026-04-30", 0),
    ]


def test_unsupported_yahoo_exchange_is_explicit(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    asset = Asset(
        id="asset-id",
        name="Acme",
        asset_type=AssetType.STOCK,
        currency="USD",
        acquisition_date=date(2026, 1, 1),
        quantity="3",
        cost_basis_native_minor=None,
        cost_basis_eur_minor=None,
        quote_symbol="ACME",
        quote_exchange="NASDAQ",
        is_active=True,
        revision=1,
    )
    with MarketDataClient(settings) as provider, pytest.raises(MarketDataError) as error:
        provider.preview(asset)
    assert error.value.code == "yahoo_exchange_unsupported"
    assert error.value.message == "Yahoo Finance is not configured for exchange NASDAQ"


def test_portfolio_openapi_contract(client: TestClient) -> None:
    openapi = client.get("/openapi.json").json()
    assert {
        "/api/v1/assets",
        "/api/v1/assets/{asset_id}",
        "/api/v1/assets/{asset_id}/valuations",
        "/api/v1/portfolio",
        "/api/v1/portfolio/history-preview",
        "/api/v1/portfolio/quote-preview",
        "/api/v1/portfolio/fx-preview",
        "/api/v1/portfolio/quote-snapshots",
    } <= openapi["paths"].keys()
    schemas = openapi["components"]["schemas"]
    assert set(schemas["AssetType"]["enum"]) == {
        "BANK_CASH",
        "BROKERAGE_CASH",
        "ETF",
        "STOCK",
        "FIXED_ASSET",
        "OTHER",
    }
    assert set(schemas["ValuationSource"]["enum"]) == {
        "MANUAL",
        "TWELVE_DATA",
        "YAHOO_FINANCE",
    }
    assert schemas["QuotePreviewReady"]["additionalProperties"] is False
    assert "preview_token" in schemas["QuotePreviewReady"]["required"]
    assert "acquisition_date" not in schemas["AssetPatch"]["properties"]


class _StubMarketDataClient:
    def __init__(self, _settings: Settings, *, fetched_at: datetime | None = None) -> None:
        self.fetched_at = fetched_at

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        pass

    def preview(self, asset: Asset) -> QuoteSnapshotData:
        if asset.quote_symbol == "FAIL":
            raise MarketDataError("quote_unavailable", "Synthetic quote failure")
        return QuoteSnapshotData(
            asset_id=asset.id,
            asset_revision=asset.revision,
            source=ValuationSource.TWELVE_DATA,
            quote_interval=QuoteInterval.LIVE,
            valued_at=date(2026, 8, 10),
            native_currency=asset.currency,
            native_value_minor=375,
            eur_value_minor=300,
            quantity=asset.quantity or "",
            unit_price="1.25",
            quote_symbol=asset.quote_symbol or "",
            quote_exchange=asset.quote_exchange,
            quote_mic_code=asset.quote_mic_code,
            quote_name=asset.name,
            quote_fetched_at=self.fetched_at or datetime.now(UTC),
            fx_source="ECB",
            fx_rate_to_eur="0.8",
            fx_rate_date=date(2026, 8, 10),
        )

    def fx_preview(self, currency: str, valued_at: date) -> FxPreviewData:
        if currency == "EUR":
            return FxPreviewData(currency, valued_at, "IDENTITY", "1", valued_at)
        if currency == "USD":
            return FxPreviewData(currency, valued_at, "ECB", "0.8", valued_at - timedelta(days=1))
        raise MarketDataError(
            "unsupported_portfolio_currency",
            "Currency is not supported by portfolio v1",
            False,
        )


class _StubYahooMarketDataClient(_StubMarketDataClient):
    def preview(self, asset: Asset) -> QuoteSnapshotData:
        return replace(super().preview(asset), source=ValuationSource.YAHOO_FINANCE)


class _StubHistoryMarketDataClient(_StubMarketDataClient):
    def history(self, asset: Asset) -> tuple[QuoteSnapshotData, ...]:
        fetched_at = datetime.now(UTC)
        base = replace(
            super().preview(asset),
            source=ValuationSource.YAHOO_FINANCE,
            quote_interval=QuoteInterval.MONTHLY,
            quote_fetched_at=fetched_at,
        )
        return (
            replace(
                base,
                valued_at=date(2026, 5, 31),
                native_value_minor=330,
                eur_value_minor=264,
                unit_price="1.1",
                fx_rate_date=date(2026, 5, 29),
            ),
            replace(
                base,
                valued_at=date(2026, 6, 30),
                native_value_minor=345,
                eur_value_minor=276,
                unit_price="1.15",
                fx_rate_date=date(2026, 6, 30),
            ),
        )


def _create_stock(client: TestClient, *, name: str = "Acme", symbol: str = "ACME") -> dict:
    response = client.post("/api/v1/assets", json=_stock_payload(name=name, symbol=symbol))
    assert response.status_code == 201, response.text
    return response.json()


def _stock_payload(*, name: str = "Acme", symbol: str = "ACME") -> dict:
    return {
        "name": name,
        "asset_type": "STOCK",
        "currency": "USD",
        "acquisition_date": "2026-07-01",
        "quantity": "3",
        "cost_basis_native_minor": 300,
        "cost_basis_eur_minor": 240,
        "cost_basis_fx_source": "MANUAL",
        "cost_basis_fx_rate_to_eur": "0.8",
        "cost_basis_fx_rate_date": "2026-07-01",
        "quote": {"symbol": symbol, "exchange": "NASDAQ"},
        "initial_valuation": {
            "valued_at": "2026-07-01",
            "native_value_minor": 300,
            "unit_price": "1",
            "fx_source": "MANUAL",
            "fx_rate_to_eur": "0.8",
            "fx_rate_date": "2026-07-01",
        },
    }
