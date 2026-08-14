from __future__ import annotations

import uuid
from calendar import monthrange
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database.models import (
    Account,
    Category,
    Subcategory,
    Transaction,
    TransactionKind,
)
from backend.app.problems import Problem
from backend.app.reporting.models import (
    AnnualMonth,
    AnnualPoint,
    BoundaryPartials,
    CompositionBreakdown,
    CumulativePoint,
    DashboardComposition,
    DashboardFilters,
    DashboardMeta,
    DashboardQuality,
    DashboardReport,
    DashboardSeries,
    DashboardSummary,
    MetricComparison,
    MonthlyCompositionItem,
    PartialPeriods,
    RankedCompositionItem,
    RecentTransaction,
    RollingMeanPoint,
    RollingMeanSeries,
    SeriesPoint,
)

REPORTING_CURRENCY = "EUR"
UNCATEGORIZED_ID = "uncategorized"
UNCATEGORIZED_NAME = "Uncategorized"


@dataclass(frozen=True, slots=True)
class _TransactionRow:
    id: str
    transaction_date: date
    amount_minor: int
    kind: TransactionKind
    category_id: str | None
    subcategory_id: str | None
    description: str
    account_id: str


@dataclass(slots=True)
class _Totals:
    income: int = 0
    spending: int = 0
    net: int = 0

    def add(self, row: _TransactionRow) -> None:
        if row.amount_minor > 0:
            self.income += row.amount_minor
        elif row.amount_minor < 0:
            self.spending += abs(row.amount_minor)
        self.net += row.amount_minor

    def include(self, other: _Totals) -> None:
        self.income += other.income
        self.spending += other.spending
        self.net += other.net


@dataclass(slots=True)
class _CompositionTotal:
    name: str
    amount: int = 0
    count: int = 0


def build_dashboard(session: Session, filters: DashboardFilters) -> DashboardReport:
    with session.no_autoflush:
        filters = _validate_filters(session, filters)
        selected_days = (filters.date_to - filters.date_from).days + 1
        prior_to = filters.date_from - timedelta(days=1)
        prior_from = prior_to - timedelta(days=selected_days - 1)
        rolling_from = _rolling_window_start(filters.date_from, "year")
        rows = _load_transactions(session, filters, min(prior_from, rolling_from))
        current_rows = [row for row in rows if row.transaction_date >= filters.date_from]
        prior_rows = [row for row in rows if prior_from <= row.transaction_date <= prior_to]
        category_names, subcategory_names, account_names = _load_names(session, current_rows)

    current_totals = _sum_rows(current_rows)
    prior_totals = _sum_rows(prior_rows)
    current_months = _period_count(filters.date_from, filters.date_to, _month_bounds)
    prior_months = _period_count(prior_from, prior_to, _month_bounds)
    current_monthly_spending = _round_divide(current_totals.spending, current_months)
    prior_monthly_spending = _round_divide(prior_totals.spending, prior_months)

    data_dates = [row.transaction_date for row in current_rows]
    return DashboardReport(
        meta=DashboardMeta(
            date_from=filters.date_from,
            date_to=filters.date_to,
            prior_from=prior_from,
            prior_to=prior_to,
            data_from=min(data_dates) if data_dates else None,
            data_to=max(data_dates) if data_dates else None,
            generated_at=datetime.now(UTC),
            currency=REPORTING_CURRENCY,
            selected_category_ids=filters.category_ids,
            selected_subcategory_ids=filters.subcategory_ids,
            partial_periods=_partial_periods(filters.date_from, filters.date_to),
        ),
        summary=DashboardSummary(
            income=_comparison(current_totals.income, prior_totals.income),
            spending=_comparison(current_totals.spending, prior_totals.spending),
            net=_comparison(current_totals.net, prior_totals.net),
            monthly_spending_mean=_comparison(current_monthly_spending, prior_monthly_spending),
        ),
        series=DashboardSeries(
            week=_build_series(current_rows, filters, _week_bounds, _week_label),
            month=_build_series(current_rows, filters, _month_bounds, _month_label),
            quarter=_build_series(current_rows, filters, _quarter_bounds, _quarter_label),
            rolling_mean=RollingMeanSeries(
                month=_build_rolling_mean(rows, filters, "month"),
                quarter=_build_rolling_mean(rows, filters, "quarter"),
                year=_build_rolling_mean(rows, filters, "year"),
            ),
        ),
        composition=_build_composition(current_rows, filters, category_names, subcategory_names),
        annual=_build_annual(current_rows, filters),
        cumulative=_build_cumulative(current_rows, filters),
        recent=_build_recent(current_rows, category_names, subcategory_names, account_names),
        quality=DashboardQuality(
            transaction_count=len(current_rows),
            uncategorized_count=sum(row.category_id is None for row in current_rows),
            category_only_count=sum(
                row.category_id is not None and row.subcategory_id is None for row in current_rows
            ),
        ),
    )


def _validate_filters(session: Session, filters: DashboardFilters) -> DashboardFilters:
    if filters.date_from > filters.date_to:
        raise Problem(
            422,
            "invalid_date_range",
            "date_from must be on or before date_to",
            field="date_from",
            recoverable=True,
        )

    category_ids = _canonical_ids(filters.category_ids, "category_id")
    subcategory_ids = _canonical_ids(filters.subcategory_ids, "subcategory_id")
    categories = dict(
        session.execute(
            select(Category.id, Category.display_name).where(Category.id.in_(category_ids))
        ).all()
    )
    missing_categories = sorted(set(category_ids) - categories.keys())
    if missing_categories:
        raise Problem(
            404,
            "category_not_found",
            "One or more categories were not found",
            field="category_id",
            recoverable=True,
            details={"ids": missing_categories},
        )

    subcategories = {
        row.id: row.category_id
        for row in session.execute(
            select(Subcategory.id, Subcategory.category_id).where(
                Subcategory.id.in_(subcategory_ids)
            )
        )
    }
    missing_subcategories = sorted(set(subcategory_ids) - subcategories.keys())
    if missing_subcategories:
        raise Problem(
            404,
            "subcategory_not_found",
            "One or more subcategories were not found",
            field="subcategory_id",
            recoverable=True,
            details={"ids": missing_subcategories},
        )
    incompatible = sorted(
        subcategory_id
        for subcategory_id, category_id in subcategories.items()
        if category_ids and category_id not in category_ids
    )
    if incompatible:
        raise Problem(
            422,
            "subcategory_parent_mismatch",
            "Subcategories must belong to a selected category",
            field="subcategory_id",
            recoverable=True,
            details={"ids": incompatible},
        )
    return DashboardFilters(
        date_from=filters.date_from,
        date_to=filters.date_to,
        category_ids=category_ids,
        subcategory_ids=subcategory_ids,
    )


def _canonical_ids(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    canonical: set[str] = set()
    for value in values:
        try:
            canonical.add(str(uuid.UUID(value)))
        except (ValueError, AttributeError) as exc:
            raise Problem(
                422,
                "invalid_taxonomy_id",
                f"{field} must contain valid UUIDs",
                field=field,
                recoverable=True,
            ) from exc
    return tuple(sorted(canonical))


def _load_transactions(
    session: Session, filters: DashboardFilters, prior_from: date
) -> list[_TransactionRow]:
    conditions = [
        Transaction.currency == REPORTING_CURRENCY,
        Transaction.is_excluded.is_(False),
        Transaction.transaction_date >= prior_from,
        Transaction.transaction_date <= filters.date_to,
    ]
    if filters.category_ids:
        conditions.append(Transaction.category_id.in_(filters.category_ids))
    if filters.subcategory_ids:
        conditions.append(Transaction.subcategory_id.in_(filters.subcategory_ids))
    result = session.execute(
        select(
            Transaction.id,
            Transaction.transaction_date,
            Transaction.amount_minor,
            Transaction.kind,
            Transaction.category_id,
            Transaction.subcategory_id,
            Transaction.description,
            Transaction.account_id,
        )
        .where(*conditions)
        .order_by(Transaction.transaction_date, Transaction.id)
    )
    return [_TransactionRow(*row) for row in result]


def _load_names(
    session: Session, rows: list[_TransactionRow]
) -> tuple[dict[str, str], dict[str, str], dict[str, str]]:
    category_ids = {row.category_id for row in rows if row.category_id is not None}
    subcategory_ids = {row.subcategory_id for row in rows if row.subcategory_id is not None}
    account_ids = {row.account_id for row in rows}
    category_names = dict(
        session.execute(
            select(Category.id, Category.display_name).where(Category.id.in_(category_ids))
        ).all()
    )
    subcategory_names = dict(
        session.execute(
            select(Subcategory.id, Subcategory.display_name).where(
                Subcategory.id.in_(subcategory_ids)
            )
        ).all()
    )
    account_names = dict(
        session.execute(select(Account.id, Account.name).where(Account.id.in_(account_ids))).all()
    )
    return category_names, subcategory_names, account_names


def _sum_rows(rows: list[_TransactionRow]) -> _Totals:
    totals = _Totals()
    for row in rows:
        totals.add(row)
    return totals


def _comparison(current: int, prior: int) -> MetricComparison:
    delta = current - prior
    percentage = None
    if prior != 0:
        percentage = _percentage(delta, abs(prior))
    return MetricComparison(
        current_minor=current,
        prior_minor=prior,
        delta_minor=delta,
        delta_percent=percentage,
    )


def _round_divide(value: int, divisor: int) -> int:
    return int((Decimal(value) / Decimal(divisor)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _percentage(numerator: int, denominator: int) -> float:
    value = Decimal(numerator) * Decimal(100) / Decimal(denominator)
    return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


PeriodBounds = Callable[[date], tuple[date, date]]
PeriodLabel = Callable[[date], str]


def _build_series(
    rows: list[_TransactionRow],
    filters: DashboardFilters,
    bounds: PeriodBounds,
    label: PeriodLabel,
) -> tuple[SeriesPoint, ...]:
    totals_by_period: defaultdict[date, _Totals] = defaultdict(_Totals)
    for row in rows:
        totals_by_period[bounds(row.transaction_date)[0]].add(row)

    points: list[SeriesPoint] = []
    period_start = bounds(filters.date_from)[0]
    while period_start <= filters.date_to:
        full_start, full_end = bounds(period_start)
        selected_start = max(full_start, filters.date_from)
        selected_end = min(full_end, filters.date_to)
        selected_days = (selected_end - selected_start).days + 1
        totals = totals_by_period[full_start]
        points.append(
            SeriesPoint(
                period_start=full_start,
                period_end=full_end,
                label=label(full_start),
                partial=selected_start != full_start or selected_end != full_end,
                selected_days=selected_days,
                income_total_minor=totals.income,
                spending_total_minor=totals.spending,
                net_total_minor=totals.net,
            )
        )
        period_start = full_end + timedelta(days=1)
    return tuple(points)


def _build_rolling_mean(
    rows: list[_TransactionRow], filters: DashboardFilters, window: str
) -> tuple[RollingMeanPoint, ...]:
    points: list[RollingMeanPoint] = []
    current = filters.date_from
    while current <= filters.date_to:
        window_start = _rolling_window_start(current, window)
        window_rows = [row for row in rows if window_start <= row.transaction_date <= current]
        totals = _sum_rows(window_rows)
        window_months = {"month": 1, "quarter": 3, "year": 12}[window]
        points.append(
            RollingMeanPoint(
                date=current,
                window_start=window_start,
                window_end=current,
                window_months=window_months,
                income_mean_minor=_round_divide(totals.income, window_months),
                spending_mean_minor=_round_divide(totals.spending, window_months),
                net_mean_minor=_round_divide(totals.net, window_months),
            )
        )
        current += timedelta(days=1)
    return tuple(points)


def _rolling_window_start(day: date, window: str) -> date:
    months = {"month": 1, "quarter": 3, "year": 12}[window]
    month_index = day.year * 12 + day.month - 1 - months
    year, zero_based_month = divmod(month_index, 12)
    month = zero_based_month + 1
    prior_day = date(year, month, min(day.day, monthrange(year, month)[1]))
    return prior_day + timedelta(days=1)


def _build_composition(
    rows: list[_TransactionRow],
    filters: DashboardFilters,
    category_names: dict[str, str],
    subcategory_names: dict[str, str],
) -> DashboardComposition:
    return DashboardComposition(
        spending=_build_composition_breakdown(
            rows,
            filters,
            category_names,
            subcategory_names,
            lambda row: abs(row.amount_minor) if row.amount_minor < 0 else None,
        ),
        income=_build_composition_breakdown(
            rows,
            filters,
            category_names,
            subcategory_names,
            lambda row: row.amount_minor if row.amount_minor > 0 else None,
        ),
    )


def _build_composition_breakdown(
    rows: list[_TransactionRow],
    filters: DashboardFilters,
    category_names: dict[str, str],
    subcategory_names: dict[str, str],
    amount_for_row: Callable[[_TransactionRow], int | None],
) -> CompositionBreakdown:
    category_monthly: dict[tuple[str, str], _CompositionTotal] = {}
    subcategory_monthly: dict[tuple[str, str], _CompositionTotal] = {}
    category_ranked: dict[str, _CompositionTotal] = {}
    subcategory_ranked: dict[str, _CompositionTotal] = {}

    for row in rows:
        amount = amount_for_row(row)
        if amount is None:
            continue
        period = row.transaction_date.strftime("%Y-%m")
        category_id, category_name = _category_identity(row, category_names)
        subcategory_id, subcategory_name = _subcategory_identity(
            row, category_names, subcategory_names
        )
        _add_composition(category_monthly, (period, category_id), category_name, amount)
        _add_composition(subcategory_monthly, (period, subcategory_id), subcategory_name, amount)
        _add_composition(category_ranked, category_id, category_name, amount)
        _add_composition(subcategory_ranked, subcategory_id, subcategory_name, amount)

    def monthly_items(
        totals: dict[tuple[str, str], _CompositionTotal],
    ) -> tuple[MonthlyCompositionItem, ...]:
        items = [
            MonthlyCompositionItem(
                period=period,
                taxonomy_id=taxonomy_id,
                name=total.name,
                amount_minor=total.amount,
                count=total.count,
                partial=_month_is_partial(period, filters),
            )
            for (period, taxonomy_id), total in totals.items()
        ]
        return tuple(
            sorted(
                items,
                key=lambda item: (item.period, item.name.casefold(), item.taxonomy_id),
            )
        )

    def ranked_items(
        totals: dict[str, _CompositionTotal],
    ) -> tuple[RankedCompositionItem, ...]:
        grand_total = sum(total.amount for total in totals.values())
        items = [
            RankedCompositionItem(
                taxonomy_id=taxonomy_id,
                name=total.name,
                amount_minor=total.amount,
                count=total.count,
                percentage=_percentage(total.amount, grand_total),
            )
            for taxonomy_id, total in totals.items()
            if grand_total
        ]
        return tuple(
            sorted(
                items,
                key=lambda item: (-item.amount_minor, item.name.casefold(), item.taxonomy_id),
            )
        )

    return CompositionBreakdown(
        category_monthly=monthly_items(category_monthly),
        subcategory_monthly=monthly_items(subcategory_monthly),
        category_ranked=ranked_items(category_ranked),
        subcategory_ranked=ranked_items(subcategory_ranked),
    )


def _add_composition(totals: dict, key: tuple[str, str] | str, name: str, amount: int) -> None:
    total = totals.setdefault(key, _CompositionTotal(name=name))
    total.amount += amount
    total.count += 1


def _category_identity(row: _TransactionRow, category_names: dict[str, str]) -> tuple[str, str]:
    if row.category_id is None:
        return UNCATEGORIZED_ID, UNCATEGORIZED_NAME
    return row.category_id, category_names[row.category_id]


def _subcategory_identity(
    row: _TransactionRow,
    category_names: dict[str, str],
    subcategory_names: dict[str, str],
) -> tuple[str, str]:
    if row.category_id is None:
        return UNCATEGORIZED_ID, UNCATEGORIZED_NAME
    if row.subcategory_id is None:
        category_name = category_names[row.category_id]
        return f"category-only:{row.category_id}", f"{category_name} (category only)"
    return row.subcategory_id, subcategory_names[row.subcategory_id]


def _month_is_partial(period: str, filters: DashboardFilters) -> bool:
    period_start = date.fromisoformat(f"{period}-01")
    _, period_end = _month_bounds(period_start)
    return filters.date_from > period_start or filters.date_to < period_end


def _build_annual(
    rows: list[_TransactionRow], filters: DashboardFilters
) -> tuple[AnnualPoint, ...]:
    monthly_totals: defaultdict[tuple[int, int], _Totals] = defaultdict(_Totals)
    for row in rows:
        monthly_totals[(row.transaction_date.year, row.transaction_date.month)].add(row)

    points: list[AnnualPoint] = []
    for year in range(filters.date_from.year, filters.date_to.year + 1):
        annual_totals = _Totals()
        months: list[AnnualMonth] = []
        for month in range(1, 13):
            totals = monthly_totals[(year, month)]
            annual_totals.include(totals)
            months.append(
                AnnualMonth(
                    month=month,
                    income_total_minor=totals.income,
                    spending_total_minor=totals.spending,
                    net_total_minor=totals.net,
                )
            )
        points.append(
            AnnualPoint(
                year=year,
                partial=filters.date_from > date(year, 1, 1)
                or filters.date_to < date(year, 12, 31),
                income_total_minor=annual_totals.income,
                spending_total_minor=annual_totals.spending,
                net_total_minor=annual_totals.net,
                income_monthly_mean_minor=_round_divide(annual_totals.income, 12),
                spending_monthly_mean_minor=_round_divide(annual_totals.spending, 12),
                net_monthly_mean_minor=_round_divide(annual_totals.net, 12),
                months=tuple(months),
            )
        )
    return tuple(points)


def _build_cumulative(
    rows: list[_TransactionRow], filters: DashboardFilters
) -> tuple[CumulativePoint, ...]:
    daily_net: defaultdict[date, int] = defaultdict(int)
    for row in rows:
        daily_net[row.transaction_date] += row.amount_minor

    cumulative = 0
    points: list[CumulativePoint] = []
    current = filters.date_from
    while current <= filters.date_to:
        net = daily_net[current]
        cumulative += net
        points.append(CumulativePoint(date=current, net_minor=net, cumulative_minor=cumulative))
        current += timedelta(days=1)
    return tuple(points)


def _build_recent(
    rows: list[_TransactionRow],
    category_names: dict[str, str],
    subcategory_names: dict[str, str],
    account_names: dict[str, str],
) -> tuple[RecentTransaction, ...]:
    recent_rows = sorted(rows, key=lambda row: (row.transaction_date, row.id), reverse=True)[:10]
    return tuple(
        RecentTransaction(
            id=row.id,
            date=row.transaction_date,
            description=row.description,
            amount_minor=row.amount_minor,
            kind=row.kind,
            category_id=row.category_id,
            category_name=category_names.get(row.category_id),
            subcategory_id=row.subcategory_id,
            subcategory_name=subcategory_names.get(row.subcategory_id),
            account_id=row.account_id,
            account_name=account_names[row.account_id],
        )
        for row in recent_rows
    )


def _partial_periods(date_from: date, date_to: date) -> PartialPeriods:
    return PartialPeriods(
        week=_boundary_partials(date_from, date_to, _week_bounds),
        month=_boundary_partials(date_from, date_to, _month_bounds),
        quarter=_boundary_partials(date_from, date_to, _quarter_bounds),
        year=_boundary_partials(date_from, date_to, _year_bounds),
    )


def _boundary_partials(date_from: date, date_to: date, bounds: PeriodBounds) -> BoundaryPartials:
    first_start, _ = bounds(date_from)
    _, last_end = bounds(date_to)
    return BoundaryPartials(first=date_from != first_start, last=date_to != last_end)


def _period_count(date_from: date, date_to: date, bounds: PeriodBounds) -> int:
    count = 0
    period_start = bounds(date_from)[0]
    while period_start <= date_to:
        count += 1
        period_start = bounds(period_start)[1] + timedelta(days=1)
    return count


def _week_bounds(value: date) -> tuple[date, date]:
    start = value - timedelta(days=value.weekday())
    return start, start + timedelta(days=6)


def _month_bounds(value: date) -> tuple[date, date]:
    start = value.replace(day=1)
    if start.month == 12:
        following = date(start.year + 1, 1, 1)
    else:
        following = date(start.year, start.month + 1, 1)
    return start, following - timedelta(days=1)


def _quarter_bounds(value: date) -> tuple[date, date]:
    start_month = ((value.month - 1) // 3) * 3 + 1
    start = date(value.year, start_month, 1)
    if start_month == 10:
        following = date(value.year + 1, 1, 1)
    else:
        following = date(value.year, start_month + 3, 1)
    return start, following - timedelta(days=1)


def _year_bounds(value: date) -> tuple[date, date]:
    return date(value.year, 1, 1), date(value.year, 12, 31)


def _week_label(value: date) -> str:
    iso_year, iso_week, _ = value.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _month_label(value: date) -> str:
    return value.strftime("%Y-%m")


def _quarter_label(value: date) -> str:
    return f"{value.year}-Q{((value.month - 1) // 3) + 1}"
