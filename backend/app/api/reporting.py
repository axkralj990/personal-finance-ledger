from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import joinedload

from backend.app.api.dependencies import SessionDependency
from backend.app.database.models import Account, Category, Transaction, TransactionKind

router = APIRouter(prefix="/reports", tags=["reports"])


class SummaryRead(BaseModel):
    currency: str
    income_minor: int
    spending_minor: int
    net_flow_minor: int


class ReportPointRead(BaseModel):
    label: str
    amount_minor: int


class ReportPointsRead(BaseModel):
    currency: str
    items: list[ReportPointRead]


class RecentTransactionRead(BaseModel):
    id: str
    transaction_date: date
    description: str
    amount_minor: int
    currency: str
    kind: TransactionKind
    account_id: str
    account_name: str
    category_id: str | None
    category_name: str | None
    subcategory_id: str | None
    subcategory_name: str | None
    is_excluded: bool
    import_batch_id: str
    revision: int


class RecentTransactionsRead(BaseModel):
    currency: str
    items: list[RecentTransactionRead]


def _conditions(currency: str, date_from: date | None, date_to: date | None) -> list[Any]:
    conditions: list[Any] = [
        Transaction.currency == currency.upper(),
        Transaction.is_excluded.is_(False),
    ]
    if date_from:
        conditions.append(Transaction.transaction_date >= date_from)
    if date_to:
        conditions.append(Transaction.transaction_date <= date_to)
    return conditions


@router.get("/summary", response_model=SummaryRead)
def report_summary(
    session: SessionDependency,
    currency: Annotated[str, Query(min_length=3, max_length=3)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> SummaryRead:
    conditions = _conditions(currency, date_from, date_to)
    row = session.execute(
        select(
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.amount_minor > 0, Transaction.amount_minor),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(
                func.sum(
                    case(
                        (Transaction.amount_minor < 0, -Transaction.amount_minor),
                        else_=0,
                    )
                ),
                0,
            ),
            func.coalesce(func.sum(Transaction.amount_minor), 0),
        ).where(*conditions)
    ).one()
    return SummaryRead(
        currency=currency.upper(),
        income_minor=int(row[0]),
        spending_minor=int(row[1]),
        net_flow_minor=int(row[2]),
    )


@router.get("/categories", response_model=ReportPointsRead)
def report_categories(
    session: SessionDependency,
    currency: Annotated[str, Query(min_length=3, max_length=3)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> ReportPointsRead:
    spending_amount = (-func.sum(Transaction.amount_minor)).label("amount_minor")
    rows = session.execute(
        select(Category.display_name, spending_amount)
        .join(Transaction, Transaction.category_id == Category.id)
        .where(
            *_conditions(currency, date_from, date_to),
            Transaction.amount_minor < 0,
        )
        .group_by(Category.id, Category.display_name)
        .order_by(spending_amount.desc())
    )
    return ReportPointsRead(
        currency=currency.upper(),
        items=[ReportPointRead(label=row[0], amount_minor=int(row[1])) for row in rows],
    )


@router.get("/accounts", response_model=ReportPointsRead)
def report_accounts(
    session: SessionDependency,
    currency: Annotated[str, Query(min_length=3, max_length=3)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> ReportPointsRead:
    rows = session.execute(
        select(Account.name, func.sum(Transaction.amount_minor))
        .join(Transaction, Transaction.account_id == Account.id)
        .where(*_conditions(currency, date_from, date_to))
        .group_by(Account.id, Account.name)
        .order_by(Account.name)
    )
    return ReportPointsRead(
        currency=currency.upper(),
        items=[ReportPointRead(label=row[0], amount_minor=int(row[1])) for row in rows],
    )


@router.get("/trend", response_model=ReportPointsRead)
def report_trend(
    session: SessionDependency,
    currency: Annotated[str, Query(min_length=3, max_length=3)],
    date_from: date | None = None,
    date_to: date | None = None,
) -> ReportPointsRead:
    """Return signed monthly net flow for included transactions."""
    period = func.strftime("%Y-%m", Transaction.transaction_date)
    rows = session.execute(
        select(period, func.sum(Transaction.amount_minor))
        .where(*_conditions(currency, date_from, date_to))
        .group_by(period)
        .order_by(period)
    )
    return ReportPointsRead(
        currency=currency.upper(),
        items=[ReportPointRead(label=row[0], amount_minor=int(row[1])) for row in rows],
    )


@router.get("/recent", response_model=RecentTransactionsRead)
def report_recent(
    session: SessionDependency,
    currency: Annotated[str, Query(min_length=3, max_length=3)],
    date_from: date | None = None,
    date_to: date | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 10,
) -> RecentTransactionsRead:
    transactions = session.scalars(
        select(Transaction)
        .options(
            joinedload(Transaction.account),
            joinedload(Transaction.category),
            joinedload(Transaction.subcategory),
        )
        .where(*_conditions(currency, date_from, date_to))
        .order_by(Transaction.transaction_date.desc(), Transaction.created_at.desc())
        .limit(limit)
    )
    return RecentTransactionsRead(
        currency=currency.upper(),
        items=[
            RecentTransactionRead(
                id=item.id,
                transaction_date=item.transaction_date,
                description=item.description,
                amount_minor=item.amount_minor,
                currency=item.currency,
                kind=item.kind,
                account_id=item.account_id,
                account_name=item.account.name,
                category_id=item.category_id,
                category_name=item.category.display_name if item.category else None,
                subcategory_id=item.subcategory_id,
                subcategory_name=item.subcategory.display_name if item.subcategory else None,
                is_excluded=item.is_excluded,
                import_batch_id=item.import_batch_id,
                revision=item.revision,
            )
            for item in transactions
        ],
    )
