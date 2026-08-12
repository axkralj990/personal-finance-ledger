import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from starlette.datastructures import UploadFile as StarletteUploadFile

from backend.app.database.models import (
    BatchStatus,
    Category,
    ImportBatch,
    Provider,
    SourceAccount,
    StagedDisposition,
    StagedTransaction,
    Transaction,
    TransactionKind,
)
from backend.app.database.session import Database


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_reporting_never_mixes_currencies(app, client: TestClient) -> None:
    database: Database = app.state.database
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "income"))
        account = SourceAccount(
            provider=Provider.MANUAL,
            display_name="Synthetic wallet",
            default_currency="EUR",
        )
        session.add(account)
        session.flush()
        batch = ImportBatch(
            source_account_id=account.id,
            original_filename="manual",
            file_sha256="f" * 64,
            parser_version="test",
            status=BatchStatus.COMMITTED,
        )
        session.add(batch)
        session.flush()
        for row_number, (currency, amount) in enumerate((("EUR", 1000), ("USD", 9000)), 1):
            staged = StagedTransaction(
                batch_id=batch.id,
                ledger_account_id=account.id,
                row_number=row_number,
                raw_json={"currency": currency},
                transaction_date=date(2026, 1, row_number),
                description="Synthetic salary",
                normalized_description="synthetic salary",
                amount_minor=amount,
                currency=currency,
                kind=TransactionKind.INCOME,
                row_fingerprint=str(row_number) * 64,
                category_id=category.id,
                disposition=StagedDisposition.COMMITTED,
            )
            session.add(staged)
            session.flush()
            session.add(
                Transaction(
                    source_account_id=account.id,
                    transaction_date=staged.transaction_date,
                    description=staged.description,
                    normalized_description=staged.normalized_description,
                    amount_minor=amount,
                    currency=currency,
                    kind=TransactionKind.INCOME,
                    category_id=category.id,
                    row_fingerprint=staged.row_fingerprint,
                    import_batch_id=batch.id,
                    staged_transaction_id=staged.id,
                )
            )
        session.commit()

    eur = client.get("/api/v1/reports/summary", params={"currency": "EUR"})
    usd = client.get("/api/v1/reports/summary", params={"currency": "USD"})
    missing = client.get("/api/v1/reports/summary")
    currencies = client.get("/api/v1/transactions/currencies")

    assert eur.status_code == 200
    assert eur.json()["income_minor"] == 1000
    assert usd.json()["income_minor"] == 9000
    assert missing.status_code == 422
    assert missing.json()["code"] == "validation_error"
    assert currencies.status_code == 200
    assert currencies.json() == ["EUR", "USD"]


def test_active_taxonomy_is_required_for_rules_and_transaction_corrections(
    app, client: TestClient
) -> None:
    database: Database = app.state.database
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        account = session.scalar(
            select(SourceAccount).where(SourceAccount.provider == Provider.MANUAL)
        )
        batch = ImportBatch(
            source_account_id=account.id,
            original_filename="taxonomy-test",
            file_sha256="1" * 64,
            parser_version="test",
            status=BatchStatus.COMMITTED,
        )
        session.add(batch)
        session.flush()
        staged = StagedTransaction(
            batch_id=batch.id,
            ledger_account_id=account.id,
            row_number=1,
            raw_json={},
            transaction_date=date(2026, 1, 1),
            description="Coffee",
            normalized_description="coffee",
            amount_minor=-450,
            currency="EUR",
            kind=TransactionKind.EXPENSE,
            row_fingerprint="2" * 64,
            category_id=category.id,
            disposition=StagedDisposition.COMMITTED,
        )
        session.add(staged)
        session.flush()
        transaction = Transaction(
            source_account_id=account.id,
            transaction_date=staged.transaction_date,
            description=staged.description,
            normalized_description=staged.normalized_description,
            amount_minor=staged.amount_minor,
            currency=staged.currency,
            kind=staged.kind,
            category_id=category.id,
            row_fingerprint=staged.row_fingerprint,
            import_batch_id=batch.id,
            staged_transaction_id=staged.id,
        )
        session.add(transaction)
        session.commit()
        category.is_active = False
        session.commit()

    rule_response = client.post(
        "/api/v1/tag-rules",
        json={
            "description": "Coffee",
            "scope": "GLOBAL",
            "category_id": category.id,
        },
    )
    transaction_response = client.patch(
        f"/api/v1/transactions/{transaction.id}",
        json={"expected_revision": 1, "category_id": category.id},
    )

    assert rule_response.status_code == 422
    assert rule_response.json()["code"] == "category_not_found"
    assert transaction_response.status_code == 422
    assert transaction_response.json()["code"] == "category_not_found"


def test_sqlite_lock_is_a_recoverable_service_unavailable(app, client: TestClient) -> None:
    @app.get("/api/test-database-lock")
    def locked() -> None:
        raise OperationalError("SELECT 1", {}, sqlite3.OperationalError("database is locked"))

    response = client.get("/api/test-database-lock")

    assert response.status_code == 503
    assert response.json() == {
        "code": "database_busy",
        "message": "The database is temporarily busy; retry the request",
        "field": None,
        "row": None,
        "recoverable": True,
        "details": None,
    }


def test_sqlite_write_requests_are_serialized(app, client: TestClient) -> None:
    state = {"active": 0, "maximum": 0}
    guard = threading.Lock()

    @app.post("/api/test-write-serialization")
    def serialized_write() -> dict[str, bool]:
        with guard:
            state["active"] += 1
            state["maximum"] = max(state["maximum"], state["active"])
        time.sleep(0.03)
        with guard:
            state["active"] -= 1
        return {"ok": True}

    with ThreadPoolExecutor(max_workers=4) as executor:
        responses = list(
            executor.map(lambda _: client.post("/api/test-write-serialization"), range(4))
        )

    assert all(response.status_code == 200 for response in responses)
    assert state["maximum"] == 1


def test_upload_stream_failure_removes_partial_file(
    app, client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_read = StarletteUploadFile.read
    calls = 0

    async def fail_after_first_read(upload, size=-1):
        nonlocal calls
        calls += 1
        if calls > 1:
            raise OSError("synthetic upload interruption")
        return await original_read(upload, size)

    monkeypatch.setattr(StarletteUploadFile, "read", fail_after_first_read)
    with app.state.database.session() as session:
        account = session.scalar(
            select(SourceAccount).where(SourceAccount.provider == Provider.LEGACY)
        )

    with pytest.raises(OSError, match="synthetic upload interruption"):
        client.post(
            "/api/v1/imports",
            data={"source_account_id": account.id},
            files={
                "file": (
                    "partial.csv",
                    b"date,description,amount\n2026-01-01,Coffee,-1\n",
                )
            },
        )

    assert list((app.state.settings.data_dir / "uploads").iterdir()) == []
