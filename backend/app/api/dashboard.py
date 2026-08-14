from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict

from backend.app.api.dependencies import SessionDependency
from backend.app.database.models import TransactionKind
from backend.app.reporting import DashboardFilters, build_dashboard

router = APIRouter(tags=["dashboard"])


class DashboardApiModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class BoundaryPartialsRead(DashboardApiModel):
    first: bool
    last: bool


class PartialPeriodsRead(DashboardApiModel):
    week: BoundaryPartialsRead
    month: BoundaryPartialsRead
    quarter: BoundaryPartialsRead
    year: BoundaryPartialsRead


class DashboardMetaRead(DashboardApiModel):
    date_from: date
    date_to: date
    prior_from: date
    prior_to: date
    data_from: date | None
    data_to: date | None
    generated_at: datetime
    currency: str
    selected_category_ids: list[str]
    selected_subcategory_ids: list[str]
    partial_periods: PartialPeriodsRead


class MetricComparisonRead(DashboardApiModel):
    current_minor: int
    prior_minor: int
    delta_minor: int
    delta_percent: float | None


class DashboardSummaryRead(DashboardApiModel):
    income: MetricComparisonRead
    spending: MetricComparisonRead
    net: MetricComparisonRead
    monthly_spending_mean: MetricComparisonRead


class SeriesPointRead(DashboardApiModel):
    period_start: date
    period_end: date
    label: str
    partial: bool
    selected_days: int
    income_total_minor: int
    spending_total_minor: int
    net_total_minor: int


class RollingMeanPointRead(DashboardApiModel):
    date: date
    window_start: date
    window_end: date
    window_months: int
    income_mean_minor: int
    spending_mean_minor: int
    net_mean_minor: int


class RollingMeanSeriesRead(DashboardApiModel):
    month: list[RollingMeanPointRead]
    quarter: list[RollingMeanPointRead]
    year: list[RollingMeanPointRead]


class DashboardSeriesRead(DashboardApiModel):
    week: list[SeriesPointRead]
    month: list[SeriesPointRead]
    quarter: list[SeriesPointRead]
    rolling_mean: RollingMeanSeriesRead


class MonthlyCompositionItemRead(DashboardApiModel):
    period: str
    taxonomy_id: str
    name: str
    amount_minor: int
    count: int
    partial: bool


class RankedCompositionItemRead(DashboardApiModel):
    taxonomy_id: str
    name: str
    amount_minor: int
    count: int
    percentage: float


class CompositionBreakdownRead(DashboardApiModel):
    category_monthly: list[MonthlyCompositionItemRead]
    subcategory_monthly: list[MonthlyCompositionItemRead]
    category_ranked: list[RankedCompositionItemRead]
    subcategory_ranked: list[RankedCompositionItemRead]


class DashboardCompositionRead(DashboardApiModel):
    spending: CompositionBreakdownRead
    income: CompositionBreakdownRead


class AnnualMonthRead(DashboardApiModel):
    month: int
    income_total_minor: int
    spending_total_minor: int
    net_total_minor: int


class AnnualPointRead(DashboardApiModel):
    year: int
    partial: bool
    income_total_minor: int
    spending_total_minor: int
    net_total_minor: int
    income_monthly_mean_minor: int
    spending_monthly_mean_minor: int
    net_monthly_mean_minor: int
    months: list[AnnualMonthRead]


class CumulativePointRead(DashboardApiModel):
    date: date
    net_minor: int
    cumulative_minor: int


class RecentTransactionRead(DashboardApiModel):
    id: str
    date: date
    description: str
    amount_minor: int
    kind: TransactionKind
    category_id: str | None
    category_name: str | None
    subcategory_id: str | None
    subcategory_name: str | None
    account_id: str
    account_name: str


class DashboardQualityRead(DashboardApiModel):
    transaction_count: int
    uncategorized_count: int
    category_only_count: int


class DashboardRead(DashboardApiModel):
    meta: DashboardMetaRead
    summary: DashboardSummaryRead
    series: DashboardSeriesRead
    composition: DashboardCompositionRead
    annual: list[AnnualPointRead]
    cumulative: list[CumulativePointRead]
    recent: list[RecentTransactionRead]
    quality: DashboardQualityRead


@router.get("/dashboard", response_model=DashboardRead)
def get_dashboard(
    session: SessionDependency,
    date_from: Annotated[date, Query()],
    date_to: Annotated[date, Query()],
    category_id: Annotated[list[str] | None, Query()] = None,
    subcategory_id: Annotated[list[str] | None, Query()] = None,
) -> DashboardRead:
    report = build_dashboard(
        session,
        DashboardFilters(
            date_from=date_from,
            date_to=date_to,
            category_ids=tuple(category_id or ()),
            subcategory_ids=tuple(subcategory_id or ()),
        ),
    )
    return DashboardRead.model_validate(report)
