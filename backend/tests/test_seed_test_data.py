import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from backend.app import cli
from backend.app.config import Settings
from backend.app.database.models import (
    Account,
    Asset,
    AssetEvent,
    AssetValuation,
    BatchStatus,
    Category,
    DuplicateStatus,
    ImportBatch,
    ImportBatchExecutionPlan,
    ImportMappingSuggestionAttempt,
    ImportMappingTemplate,
    ImportMappingTemplateVersion,
    ModelVersion,
    StagedDisposition,
    StagedTransaction,
    Subcategory,
    TagRule,
    Transaction,
    TransactionDeletion,
    TransactionEvent,
    TransactionKind,
)
from backend.app.database.session import Database
from backend.app.main import create_app
from backend.app.portfolio.service import build_portfolio
from backend.app.reporting.models import DashboardFilters
from backend.app.reporting.service import build_dashboard
from backend.app.test_data.seed import (
    CHECKING_BATCH_ID,
    CREDIT_BATCH_ID,
    DEMO_CHECKING_ID,
    DUPLICATE_BATCH_ID,
    FIXED_AT,
    IGNORED_REASON,
    IGNORED_STAGED_ID,
    IGNORED_TRANSACTION_ID,
    seed_test_data,
    synthetic_id,
)


def test_seed_has_deterministic_aggregates_and_representative_records(
    database: Database, settings: Settings
) -> None:
    summary = seed_test_data(database, settings, reset=True)

    assert summary.income_minor == 350_000
    assert summary.spending_minor == 166_945
    assert summary.net_minor == 183_055
    assert summary.transactions == 11
    with database.session() as session:
        dashboard = build_dashboard(
            session, DashboardFilters(date_from=date(2026, 1, 1), date_to=date(2026, 2, 28))
        )
        assert dashboard.summary.income.current_minor == 350_000
        assert dashboard.summary.spending.current_minor == 166_945
        assert dashboard.summary.net.current_minor == 183_055
        assert dashboard.quality.transaction_count == 10

        duplicate = session.get(StagedTransaction, synthetic_id("staged:duplicate-groceries"))
        assert duplicate.duplicate_status is DuplicateStatus.EXACT
        assert duplicate.disposition is StagedDisposition.BLOCKED
        assert duplicate.duplicate_candidate_id == synthetic_id("transaction:groceries")
        ignored = session.get(StagedTransaction, synthetic_id("staged:ignored"))
        assert ignored.disposition is StagedDisposition.IGNORE
        ignored_transaction = session.get(Transaction, IGNORED_TRANSACTION_ID)
        assert ignored_transaction.staged_transaction_id == IGNORED_STAGED_ID
        assert ignored_transaction.is_excluded is True
        assert ignored_transaction.exclusion_reason == IGNORED_REASON
        assert ignored_transaction.excluded_at == FIXED_AT.replace(tzinfo=None)
        assert session.scalar(select(func.count(Transaction.id))) == 11
        assert session.scalar(select(func.count(ImportBatch.id))) == 3
        assert {
            batch.id: (batch.total_rows, batch.included_rows, batch.ignored_rows)
            for batch in session.scalars(select(ImportBatch))
        } == {
            CHECKING_BATCH_ID: (10, 9, 1),
            CREDIT_BATCH_ID: (1, 1, 0),
            DUPLICATE_BATCH_ID: (1, 0, 0),
        }
        assert session.scalar(select(func.count(ImportMappingSuggestionAttempt.id))) == 1
        assert session.scalar(select(func.count(TransactionEvent.id))) == 1

        portfolio = build_portfolio(session, date(2026, 2, 28))
        assert portfolio.total_value_minor == 375_000
        assert session.scalar(select(func.count(Asset.id))) == 2
        assert session.scalar(select(func.count(AssetValuation.id))) == 3

    app = create_app(settings)
    with TestClient(app) as client:
        transactions = client.get("/api/v1/transactions")
        recent = client.get("/api/v1/reports/recent", params={"currency": "EUR"})
        assert transactions.status_code == 200
        assert transactions.json()["total"] == 10
        assert recent.status_code == 200
        assert len(recent.json()["items"]) == 10

    fixture_dir = settings.data_dir / "test-data"
    assert (fixture_dir / "synthetic-transactions.csv").is_file()
    assert (fixture_dir / "synthetic-credit-card.xlsx").is_file()


def test_reset_is_idempotent(database: Database, settings: Settings) -> None:
    first = seed_test_data(database, settings, reset=True)
    first_csv = (settings.data_dir / "test-data" / "synthetic-transactions.csv").read_bytes()
    first_xlsx = (settings.data_dir / "test-data" / "synthetic-credit-card.xlsx").read_bytes()
    models_dir = settings.data_dir / "models"
    models_dir.mkdir()
    orphaned_model = models_dir / "orphaned.joblib"
    orphaned_model.write_bytes(b"orphaned")

    with database.session() as session:
        transaction = session.get(Transaction, synthetic_id("transaction:salary"))
        transaction.description = "Changed locally"
        session.add(
            Account(id="arbitrary-account", name="Arbitrary account", default_currency="USD")
        )
        session.flush()
        session.add_all(
            [
                Asset(
                    id="arbitrary-asset",
                    name="Arbitrary asset",
                    asset_type="BANK_CASH",
                    currency="EUR",
                    acquisition_date=date(2026, 1, 1),
                ),
                ImportBatch(
                    id="arbitrary-batch",
                    account_id="arbitrary-account",
                    original_filename="arbitrary.csv",
                    file_sha256="a" * 64,
                    parser_version="test",
                    status=BatchStatus.COMMITTED,
                ),
                TransactionDeletion(
                    id="arbitrary-deletion",
                    transaction_id="already-deleted",
                ),
            ]
        )
        session.flush()
        session.add(
            StagedTransaction(
                id="arbitrary-staged",
                batch_id="arbitrary-batch",
                account_id="arbitrary-account",
                row_number=1,
                raw_json={"description": "Arbitrary transaction"},
                transaction_date=date(2026, 2, 20),
                description="Arbitrary transaction",
                normalized_description="arbitrary transaction",
                amount_minor=-100,
                currency="USD",
                kind=TransactionKind.EXPENSE,
                row_fingerprint="b" * 64,
                disposition=StagedDisposition.COMMITTED,
            )
        )
        session.flush()
        session.add(
            Transaction(
                id="arbitrary-transaction",
                account_id="arbitrary-account",
                transaction_date=date(2026, 2, 20),
                description="Arbitrary transaction",
                normalized_description="arbitrary transaction",
                amount_minor=-100,
                currency="USD",
                kind=TransactionKind.EXPENSE,
                row_fingerprint="b" * 64,
                import_batch_id="arbitrary-batch",
                staged_transaction_id="arbitrary-staged",
            )
        )
        session.commit()

    second = seed_test_data(database, settings, reset=True)

    assert second == first
    assert not orphaned_model.exists()
    assert (
        settings.data_dir / "test-data" / "synthetic-transactions.csv"
    ).read_bytes() == first_csv
    assert (
        settings.data_dir / "test-data" / "synthetic-credit-card.xlsx"
    ).read_bytes() == first_xlsx
    with database.session() as session:
        salary = session.get(Transaction, synthetic_id("transaction:salary"))
        assert salary.description == "Demo salary"
        assert session.get(Account, "arbitrary-account") is None
        assert session.get(Asset, "arbitrary-asset") is None
        assert session.get(ImportBatch, "arbitrary-batch") is None
        assert session.get(StagedTransaction, "arbitrary-staged") is None
        assert session.get(Transaction, "arbitrary-transaction") is None
        assert session.get(TransactionDeletion, "arbitrary-deletion") is None
        assert session.scalar(select(func.count(Transaction.id))) == 11
        assert session.scalar(select(func.count(Account.id))) == 3
        assert session.get(Account, DEMO_CHECKING_ID).created_at == FIXED_AT.replace(tzinfo=None)
        assert _business_counts(session) == {
            "accounts": 3,
            "asset_events": 0,
            "asset_valuations": 3,
            "assets": 2,
            "categories": 11,
            "import_batch_execution_plans": 0,
            "import_batches": 3,
            "import_mapping_suggestion_attempts": 1,
            "import_mapping_template_versions": 0,
            "import_mapping_templates": 0,
            "model_versions": 0,
                "staged_transactions": 12,
            "subcategories": 76,
            "tag_rules": 0,
            "transaction_deletions": 0,
            "transaction_events": 1,
                "transactions": 11,
        }
        assert session.execute(text("SELECT count(*) FROM alembic_version")).scalar_one() == 1


def test_cli_seed_test_data_command(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    database_path = tmp_path / "cli-test.sqlite3"
    settings = Settings(
        database_url=f"sqlite:///{database_path}",
        data_dir=tmp_path,
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(sys, "argv", ["personal-finance", "seed-test-data", "--reset"])

    cli.main()

    database = Database(settings.resolved_database_url)
    try:
        with database.session() as session:
            assert session.scalar(select(func.count(Transaction.id))) == 11
    finally:
        database.dispose()


def _business_counts(session) -> dict[str, int]:
    models = (
        Account,
        AssetEvent,
        AssetValuation,
        Asset,
        Category,
        ImportBatchExecutionPlan,
        ImportBatch,
        ImportMappingSuggestionAttempt,
        ImportMappingTemplateVersion,
        ImportMappingTemplate,
        ModelVersion,
        StagedTransaction,
        Subcategory,
        TagRule,
        TransactionDeletion,
        TransactionEvent,
        Transaction,
    )
    return {
        model.__tablename__: session.scalar(select(func.count()).select_from(model))
        for model in models
    }
