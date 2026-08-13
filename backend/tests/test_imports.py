from datetime import date
from pathlib import Path

import pytest
from sqlalchemy import func, select

from backend.app.database.models import (
    Account,
    Base,
    BatchStatus,
    Category,
    DuplicateStatus,
    ImportBatch,
    RuleScope,
    StagedDisposition,
    StagedTransaction,
    TagRule,
    Transaction,
    TransactionKind,
)
from backend.app.database.session import Database
from backend.app.duplicates.service import classify_duplicate
from backend.app.imports.service import ImportService
from backend.app.problems import Problem


def _batch(session, account: Account, suffix: str = "a") -> ImportBatch:
    batch = ImportBatch(
        account_id=account.id,
        original_filename=f"{suffix}.csv",
        retained_path=f"synthetic/{suffix}.csv",
        file_sha256=suffix * 64,
        parser_version="test",
        status=BatchStatus.READY,
    )
    session.add(batch)
    session.flush()
    return batch


def _staged(
    batch: ImportBatch,
    row_number: int,
    fingerprint: str,
    category_id: str,
    *,
    description: str = "Coffee House",
    amount_minor: int = -450,
    transaction_date: date = date(2026, 1, 1),
) -> StagedTransaction:
    return StagedTransaction(
        batch_id=batch.id,
        account_id=batch.account_id,
        row_number=row_number,
        raw_json={"synthetic": row_number},
        transaction_date=transaction_date,
        description=description,
        normalized_description=description.casefold(),
        amount_minor=amount_minor,
        currency="EUR",
        kind=TransactionKind.EXPENSE,
        row_fingerprint=fingerprint,
        category_id=category_id,
        disposition=StagedDisposition.INCLUDE,
    )


def test_duplicate_exact_and_likely(database: Database, account: Account) -> None:
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        batch = _batch(session, session.merge(account))
        original = _staged(batch, 1, "a" * 64, category.id)
        session.add(original)
        session.flush()
        transaction = Transaction(
            account_id=account.id,
            transaction_date=original.transaction_date,
            description=original.description,
            normalized_description=original.normalized_description,
            amount_minor=original.amount_minor,
            currency="EUR",
            kind=TransactionKind.EXPENSE,
            category_id=category.id,
            row_fingerprint=original.row_fingerprint,
            import_batch_id=batch.id,
            staged_transaction_id=original.id,
        )
        session.add(transaction)
        session.flush()

        exact = _staged(batch, 2, "a" * 64, category.id)
        exact.id = "exact-candidate"
        status, candidate_id, _ = classify_duplicate(session, exact)
        assert status == DuplicateStatus.EXACT
        assert candidate_id == transaction.id

        likely = _staged(
            batch,
            3,
            "b" * 64,
            category.id,
            description="Coffee Hause",
            transaction_date=date(2026, 1, 2),
        )
        likely.id = "likely-candidate"
        status, candidate_id, explanation = classify_duplicate(session, likely)
        assert status == DuplicateStatus.LIKELY
        assert candidate_id == transaction.id
        assert "similarity" in explanation


def test_optimistic_staged_row_update(database: Database, account: Account, tmp_path: Path) -> None:
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        batch = _batch(session, session.merge(account))
        row = _staged(batch, 1, "c" * 64, category.id)
        session.add(row)
        session.commit()
        service = ImportService(100, tmp_path)

        service.update_rows(
            session,
            batch,
            batch.revision,
            [{"id": row.id, "expected_revision": 1, "description": "New merchant"}],
        )
        assert row.revision == 2
        assert row.normalized_description == "new merchant"
        with pytest.raises(Problem) as error:
            service.update_rows(
                session,
                batch,
                batch.revision,
                [{"id": row.id, "expected_revision": 1, "description": "Stale"}],
            )
        assert error.value.status_code == 409


def test_commit_is_atomic_and_idempotent(
    database: Database, account: Account, tmp_path: Path
) -> None:
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        batch = _batch(session, session.merge(account))
        valid = _staged(batch, 1, "d" * 64, category.id, amount_minor=-100)
        invalid = _staged(batch, 2, "e" * 64, category.id, amount_minor=-200)
        invalid.validation_issues = [{"code": "synthetic_conflict"}]
        blocked = _staged(batch, 3, "f" * 64, category.id, amount_minor=-300)
        blocked.duplicate_status = DuplicateStatus.EXACT
        blocked.disposition = StagedDisposition.BLOCKED
        session.add_all([valid, invalid, blocked])
        session.commit()
        service = ImportService(100, tmp_path)

        with pytest.raises(Problem):
            service.commit(session, batch)
        assert session.scalar(select(func.count(Transaction.id))) == 0

        invalid = session.get(StagedTransaction, invalid.id)
        invalid.validation_issues = []
        session.commit()
        assert service.commit(session, batch) == 2
        assert session.scalar(select(func.count(Transaction.id))) == 2
        assert service.commit(session, batch) == 2
        assert session.scalar(select(func.count(Transaction.id))) == 2


def test_ignored_row_commits_as_excluded_and_blocks_duplicate(
    database: Database, account: Account, tmp_path: Path
) -> None:
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        batch = _batch(session, session.merge(account), "ignored")
        ignored = _staged(batch, 1, "9" * 64, category.id, amount_minor=-250)
        ignored.disposition = StagedDisposition.IGNORE
        ignored.ignore_reason = "Not part of household spending"
        session.add(ignored)
        session.commit()

        service = ImportService(100, tmp_path)
        assert service.commit(session, batch) == 0
        transaction = session.scalar(
            select(Transaction).where(Transaction.staged_transaction_id == ignored.id)
        )
        assert transaction is not None
        assert transaction.is_excluded is True
        assert transaction.exclusion_reason == "Not part of household spending"
        assert transaction.excluded_at is not None
        assert ignored.disposition == StagedDisposition.IGNORE

        duplicate_batch = _batch(session, session.merge(account), "duplicate")
        duplicate = _staged(duplicate_batch, 1, "9" * 64, category.id, amount_minor=-250)
        session.add(duplicate)
        session.flush()
        status, candidate_id, _ = classify_duplicate(session, duplicate)
        assert status == DuplicateStatus.EXACT
        assert candidate_id == transaction.id


def test_ignored_row_requires_nonblank_reason(
    database: Database, account: Account, tmp_path: Path
) -> None:
    service = ImportService(100, tmp_path)
    with database.session() as session:
        batch = service.stage_manual(
            session,
            session.merge(account),
            [
                {
                    "transaction_date": "2026-01-01",
                    "description": "Ignored",
                    "amount_minor": -100,
                    "currency": "EUR",
                }
            ],
        )
        ignored = batch.staged_rows[0]
        ignored.disposition = StagedDisposition.IGNORE
        ignored.ignore_reason = "   "
        batch.status = BatchStatus.READY
        session.commit()

        with pytest.raises(Problem, match="Ignored rows require a nonblank reason"):
            service.commit(session, batch)

        assert session.scalar(select(func.count(Transaction.id))) == 0


def test_initial_migration_does_not_call_mutable_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        Base.metadata,
        "create_all",
        lambda *args, **kwargs: pytest.fail("initial migration called metadata.create_all"),
    )
    database = Database(f"sqlite:///{tmp_path / 'explicit.sqlite3'}")
    database.migrate()
    try:
        with database.session() as session:
            assert session.scalar(select(func.count(Category.id))) == 11
    finally:
        database.dispose()


def test_manual_row_limit_and_taxonomy_are_atomic(
    database: Database, account: Account, tmp_path: Path
) -> None:
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        category.is_active = False
        session.commit()
        service = ImportService(1, tmp_path)
        row = {
            "transaction_date": "2026-01-01",
            "description": "Coffee",
            "amount_minor": -450,
            "category_id": category.id,
        }

        with pytest.raises(Problem) as too_many:
            service.stage_manual(session, session.merge(account), [row, row])
        assert too_many.value.body.code == "row_limit_exceeded"

        with pytest.raises(Problem) as invalid_taxonomy:
            service.stage_manual(session, session.merge(account), [row])
        assert invalid_taxonomy.value.body.code == "category_not_found"
        assert session.scalar(select(func.count(ImportBatch.id))) == 0
        assert session.scalar(select(func.count(StagedTransaction.id))) == 0


def test_repaired_parse_fields_are_revalidated_and_refingerprinted(
    database: Database, account: Account, tmp_path: Path
) -> None:
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        batch = _batch(session, session.merge(account))
        row = _staged(batch, 1, "0" * 64, category.id)
        row.transaction_date = None
        row.description = None
        row.normalized_description = None
        row.amount_minor = None
        row.currency = None
        row.kind = None
        row.validation_issues = [{"code": "parse_error", "message": "invalid source row"}]
        row.disposition = StagedDisposition.PENDING
        session.add(row)
        session.commit()

        ImportService(100, tmp_path).update_rows(
            session,
            batch,
            batch.revision,
            [
                {
                    "id": row.id,
                    "expected_revision": 1,
                    "transaction_date": date(2026, 2, 1),
                    "description": "Repaired coffee",
                    "amount_minor": -500,
                    "currency": "eur",
                    "kind": TransactionKind.EXPENSE,
                    "disposition": StagedDisposition.INCLUDE,
                }
            ],
        )

        assert row.validation_issues == []
        assert row.currency == "EUR"
        assert row.row_fingerprint != "0" * 64
        assert row.disposition == StagedDisposition.INCLUDE


def test_staged_edits_reject_inactive_taxonomy(
    database: Database, account: Account, tmp_path: Path
) -> None:
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        batch = _batch(session, session.merge(account))
        row = _staged(batch, 1, "5" * 64, category.id)
        session.add(row)
        session.commit()
        category.is_active = False
        session.commit()

        with pytest.raises(Problem) as error:
            ImportService(100, tmp_path).update_rows(
                session,
                batch,
                batch.revision,
                [{"id": row.id, "expected_revision": 1, "description": "Changed"}],
            )

        assert error.value.body.code == "category_not_found"
        session.refresh(row)
        assert row.description == "Coffee House"
        assert row.revision == 1


def test_stale_taxonomy_rule_is_skipped(
    database: Database, account: Account, tmp_path: Path
) -> None:
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        session.add(
            TagRule(
                normalized_description="stale merchant",
                scope=RuleScope.GLOBAL,
                category_id=category.id,
            )
        )
        session.commit()
        category.is_active = False
        session.commit()

        batch = ImportService(100, tmp_path).stage_manual(
            session,
            session.merge(account),
            [
                {
                    "transaction_date": "2026-01-01",
                    "description": "Stale Merchant",
                    "amount_minor": -100,
                }
            ],
        )

        row = batch.staged_rows[0]
        assert row.predicted_category_id is None
        assert row.category_id is None
        assert row.disposition == StagedDisposition.PENDING


@pytest.mark.parametrize(
    ("batch_status", "disposition"),
    [
        (BatchStatus.READY, StagedDisposition.IGNORE),
        (BatchStatus.READY, StagedDisposition.BLOCKED),
        (BatchStatus.READY, StagedDisposition.AUDIT_ONLY),
        (BatchStatus.READY, StagedDisposition.COMMITTED),
        (BatchStatus.FAILED, StagedDisposition.INCLUDE),
        (BatchStatus.DELETED, StagedDisposition.INCLUDE),
        (BatchStatus.COMMITTED, StagedDisposition.INCLUDE),
    ],
)
def test_ineligible_staged_rows_are_not_duplicate_candidates(
    database: Database,
    account: Account,
    batch_status: BatchStatus,
    disposition: StagedDisposition,
) -> None:
    with database.session() as session:
        category = session.scalar(select(Category).where(Category.slug == "food"))
        batch = _batch(session, session.merge(account))
        batch.status = batch_status
        candidate = _staged(batch, 1, "6" * 64, category.id)
        candidate.disposition = disposition
        session.add(candidate)
        session.flush()
        probe = _staged(batch, 2, "6" * 64, category.id)
        probe.id = "probe"

        status, candidate_id, explanation = classify_duplicate(session, probe)

        assert (status, candidate_id, explanation) == (DuplicateStatus.NONE, None, None)
