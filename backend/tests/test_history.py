import os
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.cli import migrate_history
from backend.app.config import Settings
from backend.app.database.models import (
    BatchStatus,
    DuplicateStatus,
    ImportBatch,
    SourceAccount,
    StagedDisposition,
    StagedTransaction,
    Transaction,
)
from backend.app.database.session import Database
from backend.app.sources.seed import legacy_source_account_id


def test_history_migration_routes_sources_and_commits_clean_rows(tmp_path: Path) -> None:
    history = tmp_path / "history.csv"
    history.write_text(
        "date,description,amount,source,category,subcategory,month,year,month_year\n"
        "2026-01-01,First,-1.01,DBS,lifestyle,books,1,2026,2026-01\n"
        "2026-01-02,Second,-2.02,,misc,msic,1,2026,2026-01\n"
        "2026-01-03,Third,-3.03,unknown,misc,,1,2026,2026-01\n"
        "2026-01-04,Fourth,-4.04,revolut,food,groceries,1,2026,2026-01\n"
        "2026-01-05,Fifth,-5.05,joint,food,out,1,2026,2026-01\n"
        "2026-01-06,Sixth,-6.06,matercard,transport,gas,1,2026,2026-01\n"
        "2026-01-07,Seventh,-7.07,cash,misc,gift,1,2026,2026-01\n"
        "2026-01-08,Eighth,-8.08,mastercard,transport,parking,1,2026,2026-01\n"
        "2026-01-09,Ninth,-9.09,manual,misc,documents,1,2026,2026-01\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, max_file_rows=10)
    database = Database(settings.resolved_database_url)
    database.migrate()

    migrate_history(database, settings, history, commit_clean=True)

    with database.session() as session:
        batch = session.scalar(select(ImportBatch))
        rows = list(
            session.scalars(select(StagedTransaction).order_by(StagedTransaction.row_number))
        )
        transactions = list(
            session.scalars(select(Transaction).order_by(Transaction.transaction_date))
        )
        assert batch is not None
        assert batch.total_rows == 9
        assert batch.status == BatchStatus.COMMITTED
        assert len(transactions) == 9
        assert all(row.disposition == StagedDisposition.COMMITTED for row in rows)
        assert [row.ledger_account_id for row in rows] == [
            legacy_source_account_id("dbs"),
            legacy_source_account_id("legacy"),
            legacy_source_account_id("legacy"),
            legacy_source_account_id("revolut"),
            legacy_source_account_id("joint"),
            legacy_source_account_id("mastercard"),
            legacy_source_account_id("manual"),
            legacy_source_account_id("mastercard"),
            legacy_source_account_id("manual"),
        ]
        assert [transaction.source_account_id for transaction in transactions] == [
            row.ledger_account_id for row in rows
        ]
        assert rows[0].raw_json["source"] == "DBS"
        assert rows[0].raw_json["_normalized_source"] == "dbs"
        assert rows[1].raw_json["source"] == ""
        assert rows[1].raw_json["_normalized_source"] == "legacy"
        assert rows[1].raw_json["category"] == "misc"
        assert rows[1].raw_json["subcategory"] == "msic"
        assert rows[2].raw_json["source"] == "unknown"
        assert rows[2].subcategory_id is None
        assert rows[1].subcategory_id is not None

    migrate_history(database, settings, history, commit_clean=True)
    with database.session() as session:
        assert session.scalar(select(func.count(ImportBatch.id))) == 1
        assert session.scalar(select(func.count(Transaction.id))) == 9
    database.dispose()


def test_history_clean_commit_leaves_only_conflicts_and_duplicates(tmp_path: Path) -> None:
    history = tmp_path / "history.csv"
    history.write_text(
        "date,description,amount,source,category,subcategory\n"
        "2026-01-01,Recurring,-10,revolut,food,out\n"
        "2026-01-01,Recurring,-10,revolut,food,out\n"
        "2026-01-01,RECurring,-10,revolut,food,out\n"
        "2026-01-03,Conflict,-20,,unknown,\n"
        "2026-01-04,Sub conflict,-21,,misc,unknown\n"
        "not-a-date,Invalid,-30,,misc,misc\n",
        encoding="utf-8",
    )
    settings = _settings(tmp_path, max_file_rows=10)
    database = Database(settings.resolved_database_url)
    database.migrate()

    migrate_history(database, settings, history, commit_clean=True)

    with database.session() as session:
        rows = list(
            session.scalars(select(StagedTransaction).order_by(StagedTransaction.row_number))
        )
        assert session.scalar(select(func.count(Transaction.id))) == 1
        assert [row.duplicate_status for row in rows[:3]] == [
            DuplicateStatus.NONE,
            DuplicateStatus.EXACT,
            DuplicateStatus.LIKELY,
        ]
        assert [row.disposition for row in rows] == [
            StagedDisposition.COMMITTED,
            StagedDisposition.BLOCKED,
            StagedDisposition.PENDING,
            StagedDisposition.PENDING,
            StagedDisposition.PENDING,
            StagedDisposition.PENDING,
        ]
        assert rows[3].validation_issues[0]["code"] == "taxonomy_conflict"
        assert rows[4].validation_issues[0]["code"] == "taxonomy_conflict"
        assert rows[5].validation_issues[0]["code"] == "parse_error"
    database.dispose()


REAL_HISTORY = Path(__file__).parents[2] / "data" / "dashboard" / "transactions.csv"


@pytest.mark.skipif(
    os.getenv("RUN_REAL_DATA_MIGRATION_TEST") != "1" or not REAL_HISTORY.is_file(),
    reason="requires opt-in local historical data",
)
def test_real_history_aggregate_regression(tmp_path: Path) -> None:
    settings = _settings(tmp_path, max_file_rows=5_000)
    database = Database(settings.resolved_database_url)
    database.migrate()

    migrate_history(database, settings, REAL_HISTORY, commit_clean=True)

    with database.session() as session:
        rows = list(session.scalars(select(StagedTransaction)))
        transactions = list(session.scalars(select(Transaction)))
        assert len(rows) == 2_787
        assert len(transactions) == 2_748
        assert all(row.ledger_account_id for row in rows)
        assert all(
            transaction.source_account_id == transaction.account.id for transaction in transactions
        )
        assert len(transactions) == sum(
            row.disposition == StagedDisposition.COMMITTED for row in rows
        )
        assert len(rows) == sum(
            row.disposition
            in {
                StagedDisposition.COMMITTED,
                StagedDisposition.PENDING,
                StagedDisposition.BLOCKED,
            }
            for row in rows
        )
        assert sum(row.duplicate_status == DuplicateStatus.EXACT for row in rows) == 22
        assert sum(row.duplicate_status == DuplicateStatus.LIKELY for row in rows) == 16
        assert (
            sum(
                any(issue.get("code") == "parse_error" for issue in row.validation_issues)
                for row in rows
            )
            == 1
        )
        assert (
            sum(
                any(issue.get("code") == "taxonomy_conflict" for issue in row.validation_issues)
                for row in rows
            )
            == 0
        )
        account_counts = dict(
            session.execute(
                select(SourceAccount.display_name, func.count(StagedTransaction.id))
                .join(
                    StagedTransaction,
                    StagedTransaction.ledger_account_id == SourceAccount.id,
                )
                .group_by(SourceAccount.display_name)
            ).all()
        )
        assert account_counts == {
            "DBS EUR": 141,
            "Legacy historical ledger": 2_043,
            "Manual EUR": 16,
            "Mastercard EUR": 25,
            "Revolut Joint EUR": 243,
            "Revolut Personal EUR": 319,
        }
    database.dispose()


def _settings(tmp_path: Path, *, max_file_rows: int) -> Settings:
    runtime = tmp_path / "runtime"
    return Settings(
        data_dir=runtime,
        database_url=f"sqlite:///{runtime / 'finance.sqlite3'}",
        max_file_rows=max_file_rows,
    )
