import uuid
from dataclasses import dataclass
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, inspect, select

from backend.app.api.dependencies import get_session
from backend.app.database.models import (
    Account,
    BatchStatus,
    Category,
    ImportBatch,
    StagedDisposition,
    StagedTransaction,
    Subcategory,
    Transaction,
    TransactionKind,
)
from backend.app.database.session import Database


@dataclass(frozen=True)
class TransactionInput:
    transaction_date: date
    amount_minor: int
    kind: TransactionKind
    category_id: str | None = None
    subcategory_id: str | None = None
    currency: str = "EUR"
    is_excluded: bool = False
    description: str = "Dashboard transaction"


def _taxonomy(app: FastAPI) -> dict[str, str]:
    with app.state.database.session() as session:
        food = session.scalar(select(Category).where(Category.slug == "food"))
        sport = session.scalar(select(Category).where(Category.slug == "sport"))
        income = session.scalar(select(Category).where(Category.slug == "income"))
        groceries = session.scalar(
            select(Subcategory).where(
                Subcategory.category_id == food.id,
                Subcategory.slug == "groceries",
            )
        )
        bjj = session.scalar(
            select(Subcategory).where(
                Subcategory.category_id == sport.id,
                Subcategory.slug == "bjj",
            )
        )
        return {
            "food": food.id,
            "sport": sport.id,
            "income": income.id,
            "groceries": groceries.id,
            "bjj": bjj.id,
        }


def _seed_transactions(app: FastAPI, rows: list[TransactionInput]) -> None:
    database: Database = app.state.database
    with database.session() as session:
        account = session.scalar(select(Account).where(Account.name == "Unknown"))
        batch = ImportBatch(
            account_id=account.id,
            original_filename="dashboard-test",
            file_sha256="d" * 64,
            parser_version="test",
            status=BatchStatus.COMMITTED,
        )
        session.add(batch)
        session.flush()
        for row_number, row in enumerate(rows, 1):
            fingerprint = f"{row_number:064x}"
            staged = StagedTransaction(
                batch_id=batch.id,
                account_id=account.id,
                row_number=row_number,
                raw_json={"dashboard_test": row_number},
                transaction_date=row.transaction_date,
                description=row.description,
                normalized_description=row.description.casefold(),
                amount_minor=row.amount_minor,
                currency=row.currency,
                kind=row.kind,
                row_fingerprint=fingerprint,
                category_id=row.category_id,
                subcategory_id=row.subcategory_id,
                disposition=StagedDisposition.COMMITTED,
            )
            session.add(staged)
            session.flush()
            session.add(
                Transaction(
                    account_id=account.id,
                    transaction_date=row.transaction_date,
                    description=row.description,
                    normalized_description=row.description.casefold(),
                    amount_minor=row.amount_minor,
                    currency=row.currency,
                    kind=row.kind,
                    category_id=row.category_id,
                    subcategory_id=row.subcategory_id,
                    row_fingerprint=fingerprint,
                    import_batch_id=batch.id,
                    staged_transaction_id=staged.id,
                    is_excluded=row.is_excluded,
                )
            )
        session.commit()


def test_dashboard_financial_semantics_prior_composition_recent_and_quality(
    app: FastAPI, client: TestClient
) -> None:
    taxonomy = _taxonomy(app)
    _seed_transactions(
        app,
        [
            TransactionInput(date(2025, 12, 22), 500, TransactionKind.INCOME),
            TransactionInput(date(2025, 12, 31), -100, TransactionKind.EXPENSE),
            TransactionInput(
                date(2026, 1, 1),
                1001,
                TransactionKind.INCOME,
                taxonomy["income"],
                description="Salary",
            ),
            TransactionInput(
                date(2026, 1, 2),
                -101,
                TransactionKind.EXPENSE,
                taxonomy["food"],
                taxonomy["groceries"],
                description="Groceries",
            ),
            TransactionInput(
                date(2026, 1, 3),
                -10,
                TransactionKind.EXPENSE,
                taxonomy["food"],
                description="Bank fee",
            ),
            TransactionInput(
                date(2026, 1, 4),
                40,
                TransactionKind.INCOME,
                taxonomy["food"],
                taxonomy["groceries"],
                description="Refund",
            ),
            TransactionInput(date(2026, 1, 5), -999, TransactionKind.EXPENSE),
            TransactionInput(date(2026, 1, 6), -888, TransactionKind.EXPENSE, is_excluded=True),
            TransactionInput(date(2026, 1, 7), -777, TransactionKind.EXPENSE, currency="USD"),
            TransactionInput(
                date(2026, 1, 8), -50, TransactionKind.EXPENSE, description="Cash purchase"
            ),
        ],
    )

    response = client.get(
        "/api/v1/dashboard",
        params={"date_from": "2026-01-01", "date_to": "2026-01-10"},
    )

    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["meta"]["currency"] == "EUR"
    assert dashboard["meta"]["prior_from"] == "2025-12-22"
    assert dashboard["meta"]["prior_to"] == "2025-12-31"
    assert dashboard["meta"]["data_from"] == "2026-01-01"
    assert dashboard["meta"]["data_to"] == "2026-01-08"
    assert dashboard["summary"]["income"] == {
        "current_minor": 1041,
        "prior_minor": 500,
        "delta_minor": 541,
        "delta_percent": 108.2,
    }
    assert dashboard["summary"]["spending"]["current_minor"] == 1160
    assert dashboard["summary"]["spending"]["prior_minor"] == 100
    assert dashboard["summary"]["net"]["current_minor"] == -119
    assert dashboard["summary"]["net"]["prior_minor"] == 400
    assert dashboard["summary"]["monthly_spending_mean"]["current_minor"] == 1160
    assert dashboard["quality"] == {
        "transaction_count": 6,
        "uncategorized_count": 2,
        "category_only_count": 2,
    }

    spending = dashboard["composition"]["spending"]
    category_ranked = spending["category_ranked"]
    assert [
        (item["taxonomy_id"], item["amount_minor"], item["count"]) for item in category_ranked
    ] == [
        ("uncategorized", 1049, 2),
        (taxonomy["food"], 111, 2),
    ]
    assert category_ranked[0]["percentage"] == 90.431034
    subcategory_ranked = spending["subcategory_ranked"]
    assert [item["taxonomy_id"] for item in subcategory_ranked] == [
        "uncategorized",
        taxonomy["groceries"],
        f"category-only:{taxonomy['food']}",
    ]
    assert subcategory_ranked[2]["name"] == "food (category only)"
    assert all(item["partial"] for item in spending["category_monthly"])

    income = dashboard["composition"]["income"]
    assert [
        (item["taxonomy_id"], item["amount_minor"], item["count"])
        for item in income["category_ranked"]
    ] == [
        (taxonomy["income"], 1001, 1),
        (taxonomy["food"], 40, 1),
    ]
    assert income["category_ranked"][0]["percentage"] == 96.157541
    assert [item["taxonomy_id"] for item in income["subcategory_ranked"]] == [
        f"category-only:{taxonomy['income']}",
        taxonomy["groceries"],
    ]
    assert income["subcategory_ranked"][0]["name"] == "income (category only)"
    assert all(item["partial"] for item in income["category_monthly"])

    assert len(dashboard["cumulative"]) == 10
    assert dashboard["cumulative"][0] == {
        "date": "2026-01-01",
        "net_minor": 1001,
        "cumulative_minor": 1001,
    }
    assert dashboard["cumulative"][-1]["cumulative_minor"] == -119
    assert dashboard["recent"][0]["description"] == "Cash purchase"
    assert dashboard["recent"][0]["account_name"] == "Unknown"
    assert {item["kind"] for item in dashboard["recent"]} == {
        "INCOME",
        "EXPENSE",
    }

    monthly_mean = dashboard["series"]["rolling_mean"]["month"]
    assert len(monthly_mean) == 10
    assert monthly_mean[0] == {
        "date": "2026-01-01",
        "window_start": "2025-12-02",
        "window_end": "2026-01-01",
        "window_months": 1,
        "income_mean_minor": 1501,
        "spending_mean_minor": 100,
        "net_mean_minor": 1401,
    }
    assert monthly_mean[-1] == {
        "date": "2026-01-10",
        "window_start": "2025-12-11",
        "window_end": "2026-01-10",
        "window_months": 1,
        "income_mean_minor": 1541,
        "spending_mean_minor": 1260,
        "net_mean_minor": 281,
    }
    quarter_mean = dashboard["series"]["rolling_mean"]["quarter"][0]
    assert quarter_mean["window_start"] == "2025-10-02"
    assert quarter_mean["window_months"] == 3
    assert quarter_mean["income_mean_minor"] == 500
    assert quarter_mean["spending_mean_minor"] == 33
    assert quarter_mean["net_mean_minor"] == 467


def test_dashboard_calendar_series_half_up_annual_and_zero_fill(
    app: FastAPI, client: TestClient
) -> None:
    _seed_transactions(
        app,
        [
            TransactionInput(date(2026, 1, 30), 1000, TransactionKind.INCOME),
            TransactionInput(date(2026, 1, 31), 6, TransactionKind.INCOME),
            TransactionInput(date(2026, 1, 31), -1, TransactionKind.EXPENSE),
        ],
    )

    response = client.get(
        "/api/v1/dashboard",
        params={"date_from": "2026-01-31", "date_to": "2026-02-02"},
    )

    assert response.status_code == 200
    dashboard = response.json()
    assert dashboard["meta"]["partial_periods"] == {
        "week": {"first": True, "last": True},
        "month": {"first": True, "last": True},
        "quarter": {"first": True, "last": True},
        "year": {"first": True, "last": True},
    }
    weeks = dashboard["series"]["week"]
    assert [
        (item["period_start"], item["period_end"], item["selected_days"]) for item in weeks
    ] == [
        ("2026-01-26", "2026-02-01", 2),
        ("2026-02-02", "2026-02-08", 1),
    ]
    assert weeks[0]["label"] == "2026-W05"
    rolling_month = dashboard["series"]["rolling_mean"]["month"]
    assert rolling_month[0]["window_start"] == "2026-01-01"
    assert rolling_month[0]["window_months"] == 1
    assert rolling_month[0]["income_mean_minor"] == 1006
    assert rolling_month[0]["spending_mean_minor"] == 1
    assert rolling_month[0]["net_mean_minor"] == 1005
    assert weeks[1]["income_total_minor"] == 0
    assert weeks[1]["spending_total_minor"] == 0
    assert weeks[1]["net_total_minor"] == 0

    months = dashboard["series"]["month"]
    assert [item["label"] for item in months] == ["2026-01", "2026-02"]
    assert [item["selected_days"] for item in months] == [1, 2]
    assert dashboard["series"]["quarter"][0]["label"] == "2026-Q1"
    assert dashboard["series"]["quarter"][0]["selected_days"] == 3
    assert dashboard["summary"]["monthly_spending_mean"]["current_minor"] == 1

    annual = dashboard["annual"]
    assert len(annual) == 1
    assert annual[0]["partial"] is True
    assert annual[0]["income_total_minor"] == 6
    assert annual[0]["income_monthly_mean_minor"] == 1
    assert annual[0]["spending_total_minor"] == 1
    assert annual[0]["spending_monthly_mean_minor"] == 0
    assert [month["month"] for month in annual[0]["months"]] == list(range(1, 13))
    assert annual[0]["months"][0]["net_total_minor"] == 5
    assert all(month["net_total_minor"] == 0 for month in annual[0]["months"][1:])
    assert [item["date"] for item in dashboard["cumulative"]] == [
        "2026-01-31",
        "2026-02-01",
        "2026-02-02",
    ]
    assert [item["cumulative_minor"] for item in dashboard["cumulative"]] == [5, 5, 5]


def test_dashboard_dates_are_required_inclusive_and_invalid_ranges_are_safe(
    app: FastAPI, client: TestClient
) -> None:
    _seed_transactions(
        app,
        [TransactionInput(date(2026, 3, 4), 25, TransactionKind.INCOME)],
    )

    missing = client.get("/api/v1/dashboard")
    invalid_date = client.get(
        "/api/v1/dashboard", params={"date_from": "invalid", "date_to": "2026-03-04"}
    )
    inverted = client.get(
        "/api/v1/dashboard",
        params={"date_from": "2026-03-05", "date_to": "2026-03-04"},
    )
    inclusive = client.get(
        "/api/v1/dashboard",
        params={"date_from": "2026-03-04", "date_to": "2026-03-04"},
    )

    assert missing.status_code == 422
    assert missing.json()["code"] == "validation_error"
    assert invalid_date.status_code == 422
    assert invalid_date.json()["code"] == "validation_error"
    assert inverted.status_code == 422
    assert inverted.json()["code"] == "invalid_date_range"
    assert inclusive.status_code == 200
    assert inclusive.json()["summary"]["income"]["current_minor"] == 25
    assert inclusive.json()["quality"]["transaction_count"] == 1


def test_dashboard_taxonomy_ids_relationships_and_repeated_filters(
    app: FastAPI, client: TestClient
) -> None:
    taxonomy = _taxonomy(app)
    _seed_transactions(
        app,
        [
            TransactionInput(
                date(2026, 4, 1),
                -20,
                TransactionKind.EXPENSE,
                taxonomy["food"],
                taxonomy["groceries"],
            ),
            TransactionInput(
                date(2026, 4, 2),
                -30,
                TransactionKind.EXPENSE,
                taxonomy["sport"],
                taxonomy["bjj"],
            ),
        ],
    )
    base_params = [("date_from", "2026-04-01"), ("date_to", "2026-04-30")]

    malformed = client.get(
        "/api/v1/dashboard", params=[*base_params, ("category_id", "not-a-uuid")]
    )
    nonexistent = client.get(
        "/api/v1/dashboard",
        params=[*base_params, ("category_id", str(uuid.uuid4()))],
    )
    mismatch = client.get(
        "/api/v1/dashboard",
        params=[
            *base_params,
            ("category_id", taxonomy["sport"]),
            ("subcategory_id", taxonomy["groceries"]),
        ],
    )
    repeated = client.get(
        "/api/v1/dashboard",
        params=[
            *base_params,
            ("category_id", taxonomy["sport"]),
            ("category_id", taxonomy["food"]),
            ("subcategory_id", taxonomy["groceries"]),
        ],
    )

    assert malformed.status_code == 422
    assert malformed.json()["code"] == "invalid_taxonomy_id"
    assert nonexistent.status_code == 404
    assert nonexistent.json()["code"] == "category_not_found"
    assert mismatch.status_code == 422
    assert mismatch.json()["code"] == "subcategory_parent_mismatch"
    assert repeated.status_code == 200
    assert repeated.json()["summary"]["spending"]["current_minor"] == 20
    assert repeated.json()["meta"]["selected_category_ids"] == sorted(
        [taxonomy["food"], taxonomy["sport"]]
    )
    assert repeated.json()["meta"]["selected_subcategory_ids"] == [taxonomy["groceries"]]


def test_dashboard_request_leaves_session_and_schema_unchanged(
    app: FastAPI, client: TestClient
) -> None:
    database: Database = app.state.database
    session = database.session()
    try:
        transaction_count = session.scalar(select(func.count()).select_from(Transaction))
        table_count = len(inspect(database.engine).get_table_names())

        app.dependency_overrides[get_session] = lambda: session
        response = client.get(
            "/api/v1/dashboard",
            params={"date_from": "2026-01-01", "date_to": "2026-01-31"},
        )

        assert response.status_code == 200
        assert not session.dirty
        assert not session.new
        assert not session.deleted
        assert session.scalar(select(func.count()).select_from(Transaction)) == transaction_count
        assert len(inspect(database.engine).get_table_names()) == table_count
    finally:
        app.dependency_overrides.pop(get_session, None)
        session.close()


def test_dashboard_is_registered_in_openapi(client: TestClient) -> None:
    openapi = client.get("/openapi.json").json()

    operation = openapi["paths"]["/api/v1/dashboard"]["get"]
    assert operation["tags"] == ["dashboard"]
    required_parameters = {
        parameter["name"] for parameter in operation["parameters"] if parameter["required"]
    }
    assert required_parameters == {"date_from", "date_to"}
