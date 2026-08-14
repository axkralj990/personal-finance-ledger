from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import asc, desc, func, select
from sqlalchemy.orm import joinedload

from backend.app.api.dependencies import SessionDependency
from backend.app.api.pagination import Page
from backend.app.database.models import (
    Account,
    BatchStatus,
    Category,
    DuplicateStatus,
    ImportBatch,
    StagedDisposition,
    StagedTransaction,
    Subcategory,
    Transaction,
    TransactionDeletion,
    TransactionEvent,
    TransactionKind,
    utc_now,
)
from backend.app.problems import Problem
from backend.app.sources.normalization import normalize_description
from backend.app.taxonomy.validation import validate_active_taxonomy

router = APIRouter(prefix="/transactions", tags=["transactions"])

TransactionSortField = Literal["date", "description", "account", "category", "amount"]
SortDirection = Literal["asc", "desc"]


class TransactionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    account_name: str = ""
    transaction_date: date
    transaction_at: datetime | None
    description: str
    amount_minor: int
    currency: str
    kind: TransactionKind
    category_id: str | None
    category_name: str | None = None
    subcategory_id: str | None
    subcategory_name: str | None = None
    import_batch_id: str
    is_excluded: bool
    exclusion_reason: str | None
    revision: int


class TransactionPatch(BaseModel):
    expected_revision: int = Field(ge=1)
    is_excluded: bool | None = None
    exclusion_reason: str | None = None
    description: str | None = Field(default=None, min_length=1)
    amount_minor: int | None = None
    category_id: str | None = None
    subcategory_id: str | None = None

    @field_validator("amount_minor")
    @classmethod
    def validate_amount_minor(cls, value: int | None) -> int:
        if value is None or value == 0:
            raise ValueError("amount must be non-zero")
        return value


class TransactionDelete(BaseModel):
    expected_revision: int = Field(ge=1)
    reason: Literal["USER_DELETED"] = "USER_DELETED"


@router.get("", response_model=Page[TransactionRead])
def list_transactions(
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    currency: Annotated[str | None, Query(min_length=3, max_length=3)] = None,
    date_from: date | None = None,
    date_to: date | None = None,
    account_id: str | None = None,
    category_id: str | None = None,
    search: str | None = None,
    sort_by: Annotated[TransactionSortField, Query()] = "date",
    sort_direction: Annotated[SortDirection, Query()] = "desc",
) -> Page[TransactionRead]:
    conditions = [Transaction.is_excluded.is_(False)]
    if currency:
        conditions.append(Transaction.currency == currency.upper())
    if date_from:
        conditions.append(Transaction.transaction_date >= date_from)
    if date_to:
        conditions.append(Transaction.transaction_date <= date_to)
    if account_id:
        conditions.append(Transaction.account_id == account_id)
    if category_id:
        conditions.append(Transaction.category_id == category_id)
    if search:
        conditions.append(
            Transaction.normalized_description.contains(normalize_description(search))
        )
    total = int(
        session.scalar(select(func.count()).select_from(Transaction).where(*conditions)) or 0
    )
    sort_expressions = {
        "date": (Transaction.transaction_date,),
        "description": (func.lower(Transaction.description),),
        "account": (func.lower(Account.name),),
        "category": (
            func.lower(func.coalesce(Category.display_name, "Uncategorized")),
            func.lower(func.coalesce(Subcategory.display_name, "")),
        ),
        "amount": (Transaction.amount_minor,),
    }
    order = asc if sort_direction == "asc" else desc
    order_by = [order(expression) for expression in sort_expressions[sort_by]]
    if sort_by != "date":
        order_by.append(Transaction.transaction_date.desc())
    order_by.extend((Transaction.created_at.desc(), Transaction.id.asc()))

    transactions = list(
        session.scalars(
            select(Transaction)
            .join(Account, Transaction.account_id == Account.id)
            .outerjoin(Category, Transaction.category_id == Category.id)
            .outerjoin(Subcategory, Transaction.subcategory_id == Subcategory.id)
            .options(
                joinedload(Transaction.account),
                joinedload(Transaction.category),
                joinedload(Transaction.subcategory),
            )
            .where(*conditions)
            .order_by(*order_by)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(
        items=[_transaction_read(item) for item in transactions],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/currencies", response_model=list[str])
def list_transaction_currencies(session: SessionDependency) -> list[str]:
    return list(
        session.scalars(
            select(Transaction.currency)
            .where(Transaction.is_excluded.is_(False))
            .distinct()
            .order_by(Transaction.currency)
        )
    )


@router.patch("/{transaction_id}", response_model=TransactionRead)
def patch_transaction(
    transaction_id: str, payload: TransactionPatch, session: SessionDependency
) -> TransactionRead:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None or _is_import_ignored(session, transaction):
        raise Problem(404, "transaction_not_found", "Transaction was not found")
    if transaction.revision != payload.expected_revision:
        raise Problem(
            409,
            "revision_conflict",
            "Transaction changed since it was loaded",
            recoverable=True,
            details={"current_revision": transaction.revision},
        )
    values = payload.model_dump(exclude_unset=True, exclude={"expected_revision"})
    if "amount_minor" in values:
        values["kind"] = (
            TransactionKind.INCOME if values["amount_minor"] > 0 else TransactionKind.EXPENSE
        )
    category_id = values.get("category_id", transaction.category_id)
    subcategory_id = values.get("subcategory_id", transaction.subcategory_id)
    validate_active_taxonomy(session, category_id, subcategory_id)
    previous = {key: _json_value(getattr(transaction, key)) for key in values}
    for key, value in values.items():
        setattr(transaction, key, value)
    if "description" in values:
        transaction.normalized_description = normalize_description(transaction.description)
    now = utc_now()
    if "is_excluded" in values:
        transaction.excluded_at = now if transaction.is_excluded else None
    if any(
        key in values
        for key in ("description", "amount_minor", "category_id", "subcategory_id", "kind")
    ):
        transaction.corrected_at = now
    transaction.updated_at = now
    transaction.revision += 1
    session.add(
        TransactionEvent(
            transaction_id=transaction.id,
            event_type="EXCLUSION" if "is_excluded" in values else "CORRECTION",
            previous_values=previous,
            new_values={key: _json_value(value) for key, value in values.items()},
        )
    )
    session.commit()
    return _transaction_read(transaction)


@router.delete("/{transaction_id}", status_code=204)
def delete_transaction(
    transaction_id: str,
    payload: TransactionDelete,
    session: SessionDependency,
) -> Response:
    transaction = session.get(Transaction, transaction_id)
    if transaction is None or _is_import_ignored(session, transaction):
        raise Problem(404, "transaction_not_found", "Transaction was not found")
    if transaction.revision != payload.expected_revision:
        raise Problem(
            409,
            "revision_conflict",
            "Transaction changed since it was loaded",
            recoverable=True,
            details={"current_revision": transaction.revision},
        )

    now = utc_now()
    candidate_rows = list(
        session.scalars(
            select(StagedTransaction).where(
                StagedTransaction.duplicate_candidate_id == transaction.id
            )
        )
    )
    affected_batch_ids: set[str] = set()
    for row in candidate_rows:
        row.duplicate_status = DuplicateStatus.NONE
        row.duplicate_candidate_id = None
        row.duplicate_explanation = None
        if row.disposition in {StagedDisposition.BLOCKED, StagedDisposition.PENDING}:
            row.disposition = StagedDisposition.PENDING
        row.updated_at = now
        affected_batch_ids.add(row.batch_id)

    session.add(
        TransactionDeletion(
            transaction_id=transaction.id,
            reason=payload.reason,
            deleted_at=now,
        )
    )
    session.delete(transaction)
    session.flush()

    for batch_id in affected_batch_ids:
        batch = session.get(ImportBatch, batch_id)
        if batch is None or batch.status in {BatchStatus.COMMITTED, BatchStatus.DELETED}:
            continue
        pending = session.scalar(
            select(func.count(StagedTransaction.id)).where(
                StagedTransaction.batch_id == batch_id,
                StagedTransaction.disposition == StagedDisposition.PENDING,
            )
        )
        batch.status = BatchStatus.NEEDS_REVIEW if pending else BatchStatus.READY
        batch.updated_at = now

    session.commit()
    return Response(status_code=204)


def _json_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _is_import_ignored(session: SessionDependency, transaction: Transaction) -> bool:
    staged = session.get(StagedTransaction, transaction.staged_transaction_id)
    return bool(staged and staged.disposition == StagedDisposition.IGNORE)


def _transaction_read(transaction: Transaction) -> TransactionRead:
    return TransactionRead.model_validate(transaction).model_copy(
        update={
            "account_name": transaction.account.name,
            "category_name": transaction.category.display_name if transaction.category else None,
            "subcategory_name": (
                transaction.subcategory.display_name if transaction.subcategory else None
            ),
        }
    )
