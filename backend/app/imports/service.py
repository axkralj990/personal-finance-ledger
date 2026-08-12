import hashlib
import uuid
from datetime import date
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.database.models import (
    BatchStatus,
    DuplicateStatus,
    ImportBatch,
    RuleScope,
    SourceAccount,
    StagedDisposition,
    StagedTransaction,
    TagRule,
    Transaction,
    TransactionKind,
    utc_now,
)
from backend.app.duplicates.service import classify_duplicate
from backend.app.problems import Problem
from backend.app.sources import adapter_for
from backend.app.sources.base import ParsedRow
from backend.app.sources.normalization import normalize_description, row_fingerprint
from backend.app.sources.seed import legacy_source_account_id
from backend.app.tagging.service import TaggingContext, apply_tagging, prepare_tagging
from backend.app.taxonomy.seed import resolve_taxonomy, seed_taxonomy
from backend.app.taxonomy.validation import validate_active_taxonomy


class ImportService:
    def __init__(self, max_rows: int, data_dir: Path = Path("data/runtime")) -> None:
        self.max_rows = max_rows
        self.data_dir = data_dir

    def stage_file(
        self,
        session: Session,
        account: SourceAccount,
        path: Path,
        original_filename: str,
        file_sha256: str,
    ) -> ImportBatch:
        adapter = adapter_for(account.provider)
        existing = self._active_batch(session, account.id, file_sha256)
        if existing is not None and existing.status != BatchStatus.FAILED:
            self._raise_duplicate_file(existing)

        previous_path = (
            Path(existing.retained_path) if existing and existing.retained_path else None
        )
        batch = existing or ImportBatch(source_account_id=account.id, file_sha256=file_sha256)
        batch.original_filename = original_filename
        batch.retained_path = str(path)
        batch.parser_version = adapter.parser_version
        batch.status = BatchStatus.UPLOADED
        batch.total_rows = 0
        batch.included_rows = 0
        batch.ignored_rows = 0
        batch.error_message = None
        batch.committed_at = None
        batch.updated_at = utc_now()
        if existing is not None:
            batch.staged_rows.clear()
        else:
            session.add(batch)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            winner = self._active_batch(session, account.id, file_sha256)
            if winner is None:
                raise
            self._raise_duplicate_file(winner, cause=exc)

        if previous_path is not None and previous_path != path:
            previous_path.unlink(missing_ok=True)
        try:
            parsed_rows = adapter.parse(path, account.default_currency, self.max_rows)
            self._stage_rows(session, batch, account, parsed_rows)
        except Problem as exc:
            session.rollback()
            batch = session.get(ImportBatch, batch.id)
            batch.status = BatchStatus.FAILED
            batch.error_message = exc.body.message
            batch.updated_at = utc_now()
            session.commit()
            raise
        except Exception as exc:
            session.rollback()
            batch = session.get(ImportBatch, batch.id)
            batch.status = BatchStatus.FAILED
            batch.error_message = str(exc)
            batch.updated_at = utc_now()
            session.commit()
            raise Problem(422, "parse_failed", "The uploaded file could not be parsed") from exc
        return batch

    def stage_manual(
        self, session: Session, account: SourceAccount, rows: list[dict[str, Any]]
    ) -> ImportBatch:
        if len(rows) > self.max_rows:
            raise Problem(
                413, "row_limit_exceeded", f"Import contains more than {self.max_rows} rows"
            )
        batch = ImportBatch(
            source_account_id=account.id,
            original_filename="manual-entry",
            retained_path=None,
            file_sha256=hashlib.sha256(str(uuid.uuid4()).encode()).hexdigest(),
            parser_version="manual-1",
            status=BatchStatus.UPLOADED,
        )
        session.add(batch)
        session.flush()
        parsed = [
            self._manual_row(index, raw, account.default_currency)
            for index, raw in enumerate(rows, 1)
        ]
        try:
            self._stage_rows(session, batch, account, parsed)
        except Exception:
            session.rollback()
            raise
        return batch

    def _stage_rows(
        self,
        session: Session,
        batch: ImportBatch,
        account: SourceAccount,
        parsed_rows: list[ParsedRow],
    ) -> None:
        seed_taxonomy(session)
        tagging_context: TaggingContext | None = None
        for parsed in parsed_rows:
            ledger_account = self._ledger_account_for_row(session, account, parsed)
            normalized = normalize_description(parsed.description or "")
            canonical = {
                "date": parsed.transaction_date.isoformat() if parsed.transaction_date else None,
                "timestamp": parsed.transaction_at.isoformat() if parsed.transaction_at else None,
                "description": normalized,
                "amount_minor": parsed.amount_minor,
                "currency": parsed.currency,
                "native_id": parsed.source_native_id,
            }
            staged = StagedTransaction(
                batch_id=batch.id,
                ledger_account_id=ledger_account.id,
                row_number=parsed.row_number,
                raw_json=parsed.raw,
                transaction_date=parsed.transaction_date,
                transaction_at=parsed.transaction_at,
                description=parsed.description,
                normalized_description=normalized,
                amount_minor=parsed.amount_minor,
                currency=parsed.currency,
                kind=parsed.kind,
                source_native_id=parsed.source_native_id,
                row_fingerprint=row_fingerprint(
                    ledger_account.provider.value, parsed.raw, canonical
                ),
                validation_issues=parsed.issues,
                disposition=parsed.disposition,
                ignore_reason=parsed.ignore_reason,
            )
            session.add(staged)
            session.flush()
            if parsed.category_id is not None or parsed.subcategory_id is not None:
                validate_active_taxonomy(
                    session,
                    parsed.category_id,
                    parsed.subcategory_id,
                    row=parsed.row_number,
                )
                staged.category_id = parsed.category_id
                staged.subcategory_id = parsed.subcategory_id
            elif parsed.legacy_category is not None:
                category_id, subcategory_id = resolve_taxonomy(
                    session, parsed.legacy_category, parsed.legacy_subcategory
                )
                staged.category_id = category_id
                staged.subcategory_id = subcategory_id
                if category_id is None or (
                    bool((parsed.legacy_subcategory or "").strip()) and subcategory_id is None
                ):
                    staged.validation_issues = [
                        *staged.validation_issues,
                        {
                            "code": "taxonomy_conflict",
                            "message": "Historical category or subcategory is not managed",
                        },
                    ]
            else:
                if tagging_context is None:
                    tagging_context = prepare_tagging(session, self.data_dir)
                apply_tagging(session, staged, ledger_account, tagging_context)
            duplicate_status, candidate_id, explanation = classify_duplicate(session, staged)
            staged.duplicate_status = duplicate_status
            staged.duplicate_candidate_id = candidate_id
            staged.duplicate_explanation = explanation
            if staged.disposition != StagedDisposition.AUDIT_ONLY:
                staged.disposition = self._initial_disposition(staged)
        batch.total_rows = len(parsed_rows)
        self._refresh_batch_status(batch)
        session.commit()

    def update_rows(
        self, session: Session, batch: ImportBatch, changes: list[dict[str, Any]]
    ) -> list[StagedTransaction]:
        updated = []
        with session.begin_nested():
            for change in changes:
                row = session.get(StagedTransaction, change["id"])
                if row is None or row.batch_id != batch.id:
                    raise Problem(404, "staged_row_not_found", "Staged row was not found")
                if row.revision != change["expected_revision"]:
                    raise Problem(
                        409,
                        "revision_conflict",
                        "The staged row changed since it was loaded",
                        row=row.row_number,
                        recoverable=True,
                        details={"current_revision": row.revision},
                    )
                for field in (
                    "transaction_date",
                    "description",
                    "amount_minor",
                    "currency",
                    "category_id",
                    "subcategory_id",
                    "disposition",
                    "ignore_reason",
                    "remember_correction",
                ):
                    if field in change:
                        setattr(row, field, change[field])
                if "amount_minor" in change and row.amount_minor is not None:
                    row.kind = (
                        TransactionKind.INCOME
                        if row.amount_minor > 0
                        else TransactionKind.EXPENSE
                    )
                if "currency" in change and row.currency is not None:
                    row.currency = row.currency.upper()
                if "description" in change:
                    row.normalized_description = normalize_description(row.description or "")
                if any(
                    field in change
                    for field in (
                        "transaction_date",
                        "description",
                        "amount_minor",
                        "currency",
                    )
                ):
                    self._revalidate_parse_fields(row)
                    row.row_fingerprint = self._row_fingerprint(session, row)
                if "category_id" in change or "subcategory_id" in change:
                    row.validation_issues = [
                        issue
                        for issue in row.validation_issues
                        if issue.get("code") != "taxonomy_conflict"
                    ]
                self._validate_taxonomy(session, row)
                duplicate_status, candidate_id, explanation = classify_duplicate(session, row)
                row.duplicate_status = duplicate_status
                row.duplicate_candidate_id = candidate_id
                row.duplicate_explanation = explanation
                if duplicate_status == DuplicateStatus.EXACT:
                    row.disposition = StagedDisposition.BLOCKED
                elif duplicate_status == DuplicateStatus.LIKELY and change.get(
                    "disposition"
                ) not in {
                    StagedDisposition.INCLUDE,
                    StagedDisposition.IGNORE,
                }:
                    row.disposition = StagedDisposition.PENDING
                row.revision += 1
                row.updated_at = utc_now()
                updated.append(row)
            self._refresh_batch_status(batch)
        session.commit()
        return updated

    def commit(self, session: Session, batch: ImportBatch, *, clean_only: bool = False) -> int:
        if batch.status == BatchStatus.COMMITTED:
            return batch.included_rows
        if batch.status in {BatchStatus.FAILED, BatchStatus.DELETED}:
            raise Problem(409, "batch_not_committable", "Batch cannot be committed")
        rows = list(
            session.scalars(
                select(StagedTransaction)
                .where(StagedTransaction.batch_id == batch.id)
                .order_by(StagedTransaction.row_number)
            )
        )
        pending = [row for row in rows if row.disposition == StagedDisposition.PENDING]
        if pending and not clean_only:
            raise Problem(
                409,
                "review_required",
                "All unresolved rows must be reviewed before commit",
                recoverable=True,
                details={"pending_rows": [row.row_number for row in pending]},
            )
        inserted = 0
        try:
            self._preflight_commit(session, batch, rows, clean_only)
            inserted = self._insert_included_rows(session, batch, rows)
            batch.included_rows = int(
                session.scalar(
                    select(func.count(Transaction.id)).where(
                        Transaction.import_batch_id == batch.id
                    )
                )
                or 0
            )
            batch.ignored_rows = sum(
                row.disposition
                in {
                    StagedDisposition.IGNORE,
                    StagedDisposition.BLOCKED,
                    StagedDisposition.AUDIT_ONLY,
                }
                for row in rows
            )
            unresolved = any(row.disposition == StagedDisposition.PENDING for row in rows)
            if clean_only and unresolved:
                batch.status = BatchStatus.NEEDS_REVIEW
            else:
                batch.status = BatchStatus.COMMITTED
                batch.committed_at = utc_now()
            batch.updated_at = utc_now()
            session.commit()
        except Problem:
            session.rollback()
            raise
        except IntegrityError as exc:
            session.rollback()
            raise Problem(
                409,
                "exact_duplicate",
                "A strong duplicate identity already exists",
                recoverable=True,
            ) from exc
        return inserted

    def _preflight_commit(
        self,
        session: Session,
        batch: ImportBatch,
        rows: list[StagedTransaction],
        clean_only: bool,
    ) -> None:
        discovered_duplicates: list[StagedTransaction] = []
        for row in rows:
            if row.disposition != StagedDisposition.INCLUDE:
                continue
            self._validate_row_for_commit(session, row)
            duplicate_status, candidate_id, explanation = classify_duplicate(
                session, row, check_staged=False
            )
            previous_status = row.duplicate_status
            row.duplicate_status = duplicate_status
            row.duplicate_candidate_id = candidate_id
            row.duplicate_explanation = explanation
            if duplicate_status == DuplicateStatus.EXACT:
                row.disposition = StagedDisposition.BLOCKED
                discovered_duplicates.append(row)
            elif (
                duplicate_status == DuplicateStatus.LIKELY
                and previous_status != DuplicateStatus.LIKELY
            ):
                row.disposition = StagedDisposition.PENDING
                discovered_duplicates.append(row)
        if discovered_duplicates and not clean_only:
            self._refresh_batch_status(batch)
            session.commit()
            _raise_discovered_duplicate(discovered_duplicates[0])

    @staticmethod
    def _insert_included_rows(
        session: Session, batch: ImportBatch, rows: list[StagedTransaction]
    ) -> int:
        inserted = 0
        for row in rows:
            if row.disposition != StagedDisposition.INCLUDE:
                continue
            session.add(ImportService._transaction_from_staged(batch, row))
            session.flush()
            if row.remember_correction:
                session.add(
                    TagRule(
                        normalized_description=row.normalized_description or "",
                        scope=RuleScope.ACCOUNT,
                        source_account_id=row.ledger_account_id,
                        category_id=row.category_id,
                        subcategory_id=row.subcategory_id,
                    )
                )
            row.disposition = StagedDisposition.COMMITTED
            inserted += 1
        return inserted

    @staticmethod
    def _initial_disposition(row: StagedTransaction) -> StagedDisposition:
        if row.duplicate_status == DuplicateStatus.EXACT:
            return StagedDisposition.BLOCKED
        if row.duplicate_status == DuplicateStatus.LIKELY:
            return StagedDisposition.PENDING
        if row.validation_issues or row.category_id is None:
            return StagedDisposition.PENDING
        return StagedDisposition.INCLUDE

    @staticmethod
    def _refresh_batch_status(batch: ImportBatch) -> None:
        rows = batch.staged_rows
        if any(row.disposition == StagedDisposition.PENDING for row in rows):
            batch.status = BatchStatus.NEEDS_REVIEW
        else:
            batch.status = BatchStatus.READY
        batch.updated_at = utc_now()

    @staticmethod
    def _validate_taxonomy(session: Session, row: StagedTransaction) -> None:
        validate_active_taxonomy(session, row.category_id, row.subcategory_id, row=row.row_number)

    def _validate_row_for_commit(self, session: Session, row: StagedTransaction) -> None:
        required = {
            "transaction_date": row.transaction_date,
            "description": row.description,
            "amount_minor": row.amount_minor,
            "currency": row.currency,
            "kind": row.kind,
            "category_id": row.category_id,
            "ledger_account_id": row.ledger_account_id,
        }
        missing = [name for name, value in required.items() if value is None or value == ""]
        if missing or row.validation_issues:
            raise Problem(
                422,
                "invalid_staged_row",
                "Staged row is incomplete or invalid",
                row=row.row_number,
                details={"missing": missing, "issues": row.validation_issues},
                recoverable=True,
            )
        self._validate_taxonomy(session, row)

    @staticmethod
    def _transaction_from_staged(batch: ImportBatch, row: StagedTransaction) -> Transaction:
        return Transaction(
            source_account_id=row.ledger_account_id,
            transaction_date=row.transaction_date,
            transaction_at=row.transaction_at,
            description=row.description,
            normalized_description=row.normalized_description or "",
            amount_minor=row.amount_minor,
            currency=row.currency,
            kind=row.kind,
            category_id=row.category_id,
            subcategory_id=row.subcategory_id,
            source_native_id=row.source_native_id,
            row_fingerprint=row.row_fingerprint,
            import_batch_id=batch.id,
            staged_transaction_id=row.id,
        )

    @staticmethod
    def _ledger_account_for_row(
        session: Session, batch_account: SourceAccount, parsed: ParsedRow
    ) -> SourceAccount:
        account_id = (
            legacy_source_account_id(parsed.legacy_source)
            if parsed.legacy_source is not None
            else batch_account.id
        )
        account = session.get(SourceAccount, account_id)
        if account is None:
            raise Problem(500, "source_account_missing", "Resolved source account is not seeded")
        return account

    @staticmethod
    def _manual_row(index: int, raw: dict[str, Any], default_currency: str) -> ParsedRow:
        amount_minor = int(raw["amount_minor"])
        transaction_date = raw["transaction_date"]
        if isinstance(transaction_date, str):
            transaction_date = date.fromisoformat(transaction_date)
        kind = TransactionKind.INCOME if amount_minor > 0 else TransactionKind.EXPENSE
        return ParsedRow(
            row_number=index,
            raw=raw,
            transaction_date=transaction_date,
            transaction_at=None,
            description=str(raw["description"]),
            amount_minor=amount_minor,
            currency=str(raw.get("currency") or default_currency).upper(),
            kind=kind,
            category_id=raw.get("category_id"),
            subcategory_id=raw.get("subcategory_id"),
        )

    @staticmethod
    def _active_batch(
        session: Session, source_account_id: str, file_sha256: str
    ) -> ImportBatch | None:
        return session.scalar(
            select(ImportBatch).where(
                ImportBatch.source_account_id == source_account_id,
                ImportBatch.file_sha256 == file_sha256,
                ImportBatch.status != BatchStatus.DELETED,
            )
        )

    @staticmethod
    def _raise_duplicate_file(batch: ImportBatch, *, cause: Exception | None = None) -> None:
        problem = Problem(
            409,
            "duplicate_file",
            "This file has already been imported for the source account",
            recoverable=True,
            details={"batch_id": batch.id, "status": batch.status.value},
        )
        if cause is None:
            raise problem
        raise problem from cause

    @staticmethod
    def _revalidate_parse_fields(row: StagedTransaction) -> None:
        required = {
            "transaction_date": row.transaction_date,
            "description": row.description,
            "amount_minor": row.amount_minor,
            "currency": row.currency,
            "kind": row.kind,
        }
        missing = [name for name, value in required.items() if value is None or value == ""]
        issues = [issue for issue in row.validation_issues if issue.get("code") != "parse_error"]
        if missing:
            issues.append(
                {
                    "code": "parse_error",
                    "message": f"Missing required parsed fields: {', '.join(missing)}",
                    "fields": missing,
                }
            )
        row.validation_issues = issues

    @staticmethod
    def _row_fingerprint(session: Session, row: StagedTransaction) -> str:
        account = session.get(SourceAccount, row.ledger_account_id)
        if account is None:
            raise Problem(500, "source_account_missing", "Resolved source account is not seeded")
        canonical = {
            "date": row.transaction_date.isoformat() if row.transaction_date else None,
            "timestamp": row.transaction_at.isoformat() if row.transaction_at else None,
            "description": row.normalized_description,
            "amount_minor": row.amount_minor,
            "currency": row.currency,
            "native_id": row.source_native_id,
        }
        return row_fingerprint(account.provider.value, row.raw_json, canonical)


def _raise_commit_duplicate(row: StagedTransaction) -> None:
    raise Problem(
        409,
        "exact_duplicate",
        "An exact duplicate was found during commit",
        row=row.row_number,
        recoverable=True,
    )


def _raise_discovered_duplicate(row: StagedTransaction) -> None:
    if row.duplicate_status == DuplicateStatus.EXACT:
        _raise_commit_duplicate(row)
    raise Problem(
        409,
        "duplicate_decision_required",
        "A likely duplicate discovered during commit requires review",
        row=row.row_number,
        recoverable=True,
    )
