from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from backend.app.config import Settings
from backend.app.database.models import TransactionDeletion, TransactionEvent
from backend.app.main import create_app
from backend.app.sources.seed import seed_source_accounts


def test_fresh_database_contract_flow(app, client: TestClient) -> None:  # noqa: PLR0915
    accounts_response = client.get("/api/v1/source-accounts")
    assert accounts_response.status_code == 200
    accounts = accounts_response.json()
    assert [(item["display_name"], item["default_currency"]) for item in accounts] == [
        ("DBS EUR", "EUR"),
        ("Legacy historical ledger", "EUR"),
        ("Manual EUR", "EUR"),
        ("Mastercard EUR", "EUR"),
        ("Revolut Joint EUR", "EUR"),
        ("Revolut Personal EUR", "EUR"),
    ]
    manual_account = next(item for item in accounts if item["provider"] == "MANUAL")

    with app.state.database.session() as session:
        seed_source_accounts(session)
    assert len(client.get("/api/v1/source-accounts").json()) == 6

    category_response = client.post(
        "/api/v1/categories", json={"display_name": "Contract spending"}
    )
    assert category_response.status_code == 201
    category = category_response.json()
    subcategory_response = client.post(
        "/api/v1/categories",
        json={
            "display_name": "Contract coffee",
            "parent_category_id": category["id"],
        },
    )
    assert subcategory_response.status_code == 201
    subcategory = subcategory_response.json()
    renamed = client.patch(
        f"/api/v1/categories/{subcategory['id']}",
        json={"display_name": "Contract cafes", "is_active": False},
    )
    assert renamed.status_code == 200
    assert renamed.json()["display_name"] == "Contract cafes"
    assert renamed.json()["is_active"] is False

    income_category = next(
        item for item in client.get("/api/v1/categories").json() if item["slug"] == "income"
    )
    manual_response = client.post(
        "/api/v1/manual-imports",
        json={
            "source_account_id": manual_account["id"],
            "rows": [
                {
                    "transaction_date": "2026-01-10",
                    "description": "January coffee",
                    "amount_minor": -1250,
                    "currency": "EUR",
                    "category_id": category["id"],
                },
                {
                    "transaction_date": "2026-02-10",
                    "description": "February coffee",
                    "amount_minor": -500,
                    "currency": "EUR",
                    "category_id": category["id"],
                },
                {
                    "transaction_date": "2026-02-11",
                    "description": "Contract income",
                    "amount_minor": 3000,
                    "currency": "EUR",
                    "category_id": income_category["id"],
                },
                {
                    "transaction_date": "2026-02-12",
                    "description": "Internal movement",
                    "amount_minor": -100,
                    "currency": "EUR",
                    "category_id": category["id"],
                },
            ],
        },
    )
    assert manual_response.status_code == 201
    batch = manual_response.json()
    assert batch["valid_rows"] == 4
    assert batch["needs_review_rows"] == 0
    assert batch["duplicate_rows"] == 0
    assert batch["errors"] == []

    first_page = client.get(
        f"/api/v1/imports/{batch['id']}/rows", params={"page": 1, "page_size": 2}
    )
    second_page = client.get(
        f"/api/v1/imports/{batch['id']}/rows", params={"page": 2, "page_size": 2}
    )
    assert first_page.status_code == 200
    assert first_page.json()["total"] == 4
    assert len(first_page.json()["items"]) == 2
    assert len(second_page.json()["items"]) == 2
    assert second_page.json()["items"][1]["kind"] == "EXPENSE"
    assert first_page.json()["items"][0]["raw_json"]["transaction_date"] == "2026-01-10"
    assert first_page.json()["items"][0]["duplicate_candidate"] is None

    committed = client.post(f"/api/v1/imports/{batch['id']}/commit")
    assert committed.status_code == 200
    assert committed.json()["status"] == "COMMITTED"

    account_filter = client.get(
        "/api/v1/transactions",
        params={"source_account_id": manual_account["id"], "page_size": 10},
    )
    assert account_filter.status_code == 200
    assert account_filter.json()["total"] == 4
    assert account_filter.json()["items"][0]["source_account_name"] == "Manual EUR"
    category_filter = client.get(
        "/api/v1/transactions", params={"category_id": category["id"], "page_size": 10}
    )
    assert category_filter.json()["total"] == 3
    february_filter = client.get(
        "/api/v1/transactions",
        params={"date_from": "2026-02-01", "date_to": "2026-02-28", "page_size": 10},
    )
    assert february_filter.json()["total"] == 3
    description_search = client.get(
        "/api/v1/transactions", params={"search": "FEBRUARY COFFEE", "page_size": 10}
    )
    assert description_search.json()["total"] == 1
    february_transaction = description_search.json()["items"][0]
    sign_corrected = client.patch(
        f"/api/v1/transactions/{february_transaction['id']}",
        json={"expected_revision": february_transaction["revision"], "amount_minor": 500},
    )
    assert sign_corrected.json()["amount_minor"] == 500
    assert sign_corrected.json()["kind"] == "INCOME"

    report_params = {
        "currency": "EUR",
        "date_from": "2026-01-01",
        "date_to": "2026-01-31",
    }
    summary = client.get("/api/v1/reports/summary", params=report_params)
    categories = client.get("/api/v1/reports/categories", params=report_params)
    account_report = client.get("/api/v1/reports/accounts", params=report_params)
    trend = client.get("/api/v1/reports/trend", params=report_params)
    recent = client.get("/api/v1/reports/recent", params=report_params)
    assert summary.json()["spending_minor"] == 1250
    assert summary.json()["net_flow_minor"] == -1250
    assert categories.json()["items"] == [{"label": "Contract spending", "amount_minor": 1250}]
    assert account_report.json()["items"] == [{"label": "Manual EUR", "amount_minor": -1250}]
    assert trend.json()["items"] == [{"label": "2026-01", "amount_minor": -1250}]
    assert recent.json()["items"][0]["category_name"] == "Contract spending"

    duplicate_batch = client.post(
        "/api/v1/manual-imports",
        json={
            "source_account_id": manual_account["id"],
            "rows": [
                {
                    "transaction_date": "2026-01-11",
                    "description": "January coffee",
                    "amount_minor": -1250,
                    "currency": "EUR",
                    "category_id": category["id"],
                }
            ],
        },
    ).json()
    assert duplicate_batch["duplicate_rows"] == 1
    assert duplicate_batch["needs_review_rows"] == 1
    duplicate_row = client.get(f"/api/v1/imports/{duplicate_batch['id']}/rows").json()["items"][0]
    assert duplicate_row["duplicate_status"] == "LIKELY"
    assert duplicate_row["disposition"] == "PENDING"
    assert duplicate_row["duplicate_candidate"] == {
        "id": recent.json()["items"][0]["id"],
        "transaction_date": "2026-01-10",
        "description": "January coffee",
        "amount_minor": -1250,
        "currency": "EUR",
        "source_account_name": "Manual EUR",
    }

    january_transaction = recent.json()["items"][0]
    zero_amount = client.patch(
        f"/api/v1/transactions/{january_transaction['id']}",
        json={"expected_revision": january_transaction["revision"], "amount_minor": 0},
    )
    assert zero_amount.status_code == 422
    amount_corrected = client.patch(
        f"/api/v1/transactions/{january_transaction['id']}",
        json={"expected_revision": january_transaction["revision"], "amount_minor": -1500},
    )
    assert amount_corrected.status_code == 200
    assert amount_corrected.json()["amount_minor"] == -1500
    assert amount_corrected.json()["kind"] == "EXPENSE"
    with app.state.database.session() as session:
        correction = session.scalar(
            select(TransactionEvent)
            .where(
                TransactionEvent.transaction_id == january_transaction["id"],
                TransactionEvent.event_type == "CORRECTION",
            )
            .order_by(TransactionEvent.created_at.desc())
        )
        assert correction is not None
        assert correction.previous_values["amount_minor"] == -1250
        assert correction.new_values["amount_minor"] == -1500
    assert (
        client.get("/api/v1/reports/summary", params=report_params).json()["spending_minor"] == 1500
    )
    patched = client.patch(
        f"/api/v1/transactions/{january_transaction['id']}",
        json={"expected_revision": amount_corrected.json()["revision"], "is_excluded": True},
    )
    assert patched.status_code == 200
    assert patched.json()["is_excluded"] is True
    assert patched.json()["source_account_name"] == "Manual EUR"
    assert client.get("/api/v1/reports/summary", params=report_params).json()["spending_minor"] == 0

    stale_delete = client.request(
        "DELETE",
        f"/api/v1/transactions/{january_transaction['id']}",
        json={"expected_revision": january_transaction["revision"]},
    )
    assert stale_delete.status_code == 409
    deleted = client.request(
        "DELETE",
        f"/api/v1/transactions/{january_transaction['id']}",
        json={"expected_revision": patched.json()["revision"], "reason": "USER_DELETED"},
    )
    assert deleted.status_code == 204
    refreshed_duplicate = client.get(f"/api/v1/imports/{duplicate_batch['id']}/rows").json()[
        "items"
    ][0]
    assert refreshed_duplicate["duplicate_status"] == "NONE"
    assert refreshed_duplicate["duplicate_candidate"] is None
    with app.state.database.session() as session:
        tombstone = session.scalar(
            select(TransactionDeletion).where(
                TransactionDeletion.transaction_id == january_transaction["id"]
            )
        )
        assert tombstone is not None
        assert tombstone.reason == "USER_DELETED"

    assert client.delete(f"/api/v1/imports/{duplicate_batch['id']}").status_code == 204
    replacement = client.post(
        "/api/v1/manual-imports",
        json={
            "source_account_id": manual_account["id"],
            "rows": [
                {
                    "transaction_date": "2026-01-10",
                    "description": "January coffee",
                    "amount_minor": -1250,
                    "currency": "EUR",
                    "category_id": category["id"],
                }
            ],
        },
    )
    assert replacement.status_code == 201
    assert replacement.json()["duplicate_rows"] == 0
    recommitted = client.post(f"/api/v1/imports/{replacement.json()['id']}/commit")
    assert recommitted.status_code == 200

    openapi = client.get("/openapi.json").json()
    assert "/api/v1/reports/categories" in openapi["paths"]
    transaction_schema = openapi["components"]["schemas"]["TransactionRead"]["properties"]
    assert "source_account_name" in transaction_schema
    assert "is_excluded" in transaction_schema
    assert "delete" in openapi["paths"]["/api/v1/transactions/{transaction_id}"]


def test_spa_fallback_never_turns_api_404_into_html(tmp_path: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>ledger</html>", encoding="utf-8")
    (dist / "app.js").write_text("window.ledger = true", encoding="utf-8")
    settings = Settings(
        data_dir=tmp_path / "runtime",
        database_url=f"sqlite:///{tmp_path / 'runtime' / 'finance.sqlite3'}",
        frontend_dist_path=dist,
    )

    with TestClient(create_app(settings)) as client:
        spa = client.get("/transactions")
        asset = client.get("/app.js")
        api_missing = client.get("/api/v1/not-a-route")

    assert spa.status_code == 200
    assert "ledger" in spa.text
    assert asset.status_code == 200
    assert "window.ledger" in asset.text
    assert api_missing.status_code == 404
    assert api_missing.headers["content-type"].startswith("application/json")
    assert api_missing.json()["code"] == "not_found"
