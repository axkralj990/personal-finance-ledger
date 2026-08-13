from datetime import timedelta

from rapidfuzz.fuzz import ratio
from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from backend.app.database.models import (
    BatchStatus,
    DuplicateStatus,
    ImportBatch,
    StagedDisposition,
    StagedTransaction,
    Transaction,
)

DRAFT_BATCH_STATUSES = {
    BatchStatus.UPLOADED,
    BatchStatus.AWAITING_MAPPING,
    BatchStatus.STAGING,
    BatchStatus.PARSED,
    BatchStatus.NEEDS_REVIEW,
    BatchStatus.READY,
}
DRAFT_DISPOSITIONS = {StagedDisposition.PENDING, StagedDisposition.INCLUDE}


def classify_duplicate(
    session: Session,
    staged: StagedTransaction,
    *,
    check_staged: bool = True,
) -> tuple[DuplicateStatus, str | None, str | None]:
    exact = _find_exact_duplicate(session, staged, check_staged)
    if exact is not None:
        return exact

    candidate_query = _likely_candidates(staged)
    if candidate_query is None:
        return DuplicateStatus.NONE, None, None
    best: tuple[float, Transaction, int] | None = None
    for candidate in session.scalars(candidate_query):
        days = abs((candidate.transaction_date - staged.transaction_date).days)
        similarity = ratio(candidate.normalized_description, staged.normalized_description or "")
        if similarity < 85:
            continue
        score = similarity - days * 5
        if best is None or score > best[0]:
            best = (score, candidate, days)
    if best is None:
        return _find_likely_staged_duplicate(session, staged, check_staged)
    _, candidate, days = best
    similarity = ratio(candidate.normalized_description, staged.normalized_description or "")
    explanation = (
        f"Same account, currency and amount; {days} day(s) apart; "
        f"description similarity {similarity:.0f}%"
    )
    return DuplicateStatus.LIKELY, candidate.id, explanation


def _find_exact_duplicate(
    session: Session,
    staged: StagedTransaction,
    check_staged: bool,
) -> tuple[DuplicateStatus, str | None, str] | None:
    if staged.source_native_id:
        native_match = session.scalar(
            select(Transaction).where(
                Transaction.account_id == staged.account_id,
                Transaction.source_native_id == staged.source_native_id,
            )
        )
        if native_match:
            return DuplicateStatus.EXACT, native_match.id, "Same provider-native transaction ID"
        if check_staged:
            staged_native_match = session.scalar(
                select(StagedTransaction)
                .join(ImportBatch)
                .where(
                    StagedTransaction.account_id == staged.account_id,
                    ImportBatch.status.in_(DRAFT_BATCH_STATUSES),
                    StagedTransaction.disposition.in_(DRAFT_DISPOSITIONS),
                    StagedTransaction.source_native_id == staged.source_native_id,
                    StagedTransaction.id != staged.id,
                )
            )
            if staged_native_match:
                return (
                    DuplicateStatus.EXACT,
                    None,
                    "Same provider-native transaction ID in another draft",
                )

    if staged.row_fingerprint:
        fingerprint_match = session.scalar(
            select(Transaction).where(
                Transaction.account_id == staged.account_id,
                Transaction.row_fingerprint == staged.row_fingerprint,
            )
        )
        if fingerprint_match:
            return DuplicateStatus.EXACT, fingerprint_match.id, "Same provider row fingerprint"
        if check_staged:
            staged_match = session.scalar(
                select(StagedTransaction)
                .join(ImportBatch)
                .where(
                    StagedTransaction.account_id == staged.account_id,
                    ImportBatch.status.in_(DRAFT_BATCH_STATUSES),
                    StagedTransaction.disposition.in_(DRAFT_DISPOSITIONS),
                    StagedTransaction.row_fingerprint == staged.row_fingerprint,
                    StagedTransaction.id != staged.id,
                )
            )
            if staged_match:
                return DuplicateStatus.EXACT, None, "Same provider row fingerprint in another draft"

    return None


def _likely_candidates(
    staged: StagedTransaction,
) -> Select[tuple[Transaction]] | None:
    if (
        staged.transaction_date is None
        or staged.currency is None
        or staged.amount_minor is None
        or not staged.normalized_description
    ):
        return None
    return select(Transaction).where(
        Transaction.account_id == staged.account_id,
        Transaction.currency == staged.currency,
        Transaction.amount_minor == staged.amount_minor,
        Transaction.transaction_date.between(
            staged.transaction_date - timedelta(days=3),
            staged.transaction_date + timedelta(days=3),
        ),
    )


def _find_likely_staged_duplicate(
    session: Session, staged: StagedTransaction, check_staged: bool
) -> tuple[DuplicateStatus, str | None, str | None]:
    if not check_staged or staged.transaction_date is None or not staged.normalized_description:
        return DuplicateStatus.NONE, None, None
    candidates = session.scalars(
        select(StagedTransaction)
        .join(ImportBatch)
        .where(
            StagedTransaction.account_id == staged.account_id,
            StagedTransaction.id != staged.id,
            StagedTransaction.currency == staged.currency,
            StagedTransaction.amount_minor == staged.amount_minor,
            StagedTransaction.transaction_date.between(
                staged.transaction_date - timedelta(days=3),
                staged.transaction_date + timedelta(days=3),
            ),
            ImportBatch.status.in_(DRAFT_BATCH_STATUSES),
            StagedTransaction.disposition.in_(DRAFT_DISPOSITIONS),
        )
    )
    best: tuple[float, int] | None = None
    for candidate in candidates:
        if candidate.transaction_date is None:
            continue
        days = abs((candidate.transaction_date - staged.transaction_date).days)
        similarity = ratio(candidate.normalized_description or "", staged.normalized_description)
        if similarity < 85:
            continue
        score = similarity - days * 5
        if best is None or score > best[0]:
            best = (score, days)
    if best is None:
        return DuplicateStatus.NONE, None, None
    _, days = best
    return (
        DuplicateStatus.LIKELY,
        None,
        f"Same account, currency and amount as another draft row; {days} day(s) apart",
    )
