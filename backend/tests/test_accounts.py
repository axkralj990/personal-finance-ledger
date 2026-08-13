from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from backend.app.database.models import (
    Account,
    BatchStatus,
    ImportBatch,
    StagedDisposition,
    StagedTransaction,
    Transaction,
    TransactionKind,
)


def test_account_crud_and_deactivation(client: TestClient) -> None:
    assert client.get("/api/v1/source-accounts").status_code == 404
    initial = client.get("/api/v1/accounts")
    assert initial.status_code == 200
    assert [account["name"] for account in initial.json()] == ["Unknown"]
    assert all("provider" not in account for account in initial.json())

    created = client.post(
        "/api/v1/accounts", json={"name": " Daily Wallet ", "default_currency": "sgd"}
    )
    assert created.status_code == 201
    assert created.json()["name"] == "Daily Wallet"
    assert created.json()["default_currency"] == "SGD"

    account_id = created.json()["id"]
    updated = client.patch(f"/api/v1/accounts/{account_id}", json={"name": "Cash"})
    assert updated.status_code == 200
    assert updated.json()["name"] == "Cash"

    deactivated = client.post(f"/api/v1/accounts/{account_id}/deactivate")
    assert deactivated.status_code == 200
    assert deactivated.json()["is_active"] is False


def test_account_currency_requires_exact_iso_4217_code(app, client: TestClient) -> None:
    invalid = client.post(
        "/api/v1/accounts", json={"name": "Invalid currency", "default_currency": "ZZZ"}
    )
    assert invalid.status_code == 422

    with app.state.database.session() as session, pytest.raises(IntegrityError):
        session.execute(
            text(
                "INSERT INTO accounts "
                "(id, name, default_currency, is_active, created_at, updated_at) "
                "VALUES ('invalid', 'Invalid', 'ZZZ', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            )
        )
        session.commit()


def test_include_excluded_query_cannot_bypass_normal_visibility(app, client: TestClient) -> None:
    with app.state.database.session() as session:
        account = session.scalar(select(Account).where(Account.name == "Unknown"))
        batch = ImportBatch(
            account_id=account.id,
            original_filename="ignored",
            file_sha256="e" * 64,
            parser_version="test",
            status=BatchStatus.COMMITTED,
        )
        session.add(batch)
        session.flush()
        staged = StagedTransaction(
            batch_id=batch.id,
            account_id=account.id,
            row_number=1,
            raw_json={},
            transaction_date=date(2026, 1, 1),
            description="Ignored",
            normalized_description="ignored",
            amount_minor=-100,
            currency="EUR",
            kind=TransactionKind.EXPENSE,
            row_fingerprint="f" * 64,
            disposition=StagedDisposition.IGNORE,
        )
        session.add(staged)
        session.flush()
        transaction = Transaction(
            account_id=account.id,
            transaction_date=staged.transaction_date,
            description="Ignored",
            normalized_description="ignored",
            amount_minor=-100,
            currency="EUR",
            kind=TransactionKind.EXPENSE,
            row_fingerprint=staged.row_fingerprint,
            import_batch_id=batch.id,
            staged_transaction_id=staged.id,
            is_excluded=True,
            exclusion_reason="ignored",
        )
        session.add(transaction)
        session.commit()

    response = client.get("/api/v1/transactions", params={"include_excluded": True})
    assert response.status_code == 200
    assert response.json()["items"] == []
    assert (
        client.patch(
            f"/api/v1/transactions/{transaction.id}",
            json={"expected_revision": 1, "description": "Visible"},
        ).status_code
        == 404
    )
