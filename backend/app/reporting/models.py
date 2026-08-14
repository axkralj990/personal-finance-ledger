from dataclasses import dataclass
from datetime import date, datetime

from backend.app.database.models import TransactionKind


@dataclass(frozen=True, slots=True)
class DashboardFilters:
    date_from: date
    date_to: date
    category_ids: tuple[str, ...] = ()
    subcategory_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BoundaryPartials:
    first: bool
    last: bool


@dataclass(frozen=True, slots=True)
class PartialPeriods:
    week: BoundaryPartials
    month: BoundaryPartials
    quarter: BoundaryPartials
    year: BoundaryPartials


@dataclass(frozen=True, slots=True)
class DashboardMeta:
    date_from: date
    date_to: date
    prior_from: date
    prior_to: date
    data_from: date | None
    data_to: date | None
    generated_at: datetime
    currency: str
    selected_category_ids: tuple[str, ...]
    selected_subcategory_ids: tuple[str, ...]
    partial_periods: PartialPeriods


@dataclass(frozen=True, slots=True)
class MetricComparison:
    current_minor: int
    prior_minor: int
    delta_minor: int
    delta_percent: float | None


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    income: MetricComparison
    spending: MetricComparison
    net: MetricComparison
    monthly_spending_mean: MetricComparison


@dataclass(frozen=True, slots=True)
class SeriesPoint:
    period_start: date
    period_end: date
    label: str
    partial: bool
    selected_days: int
    income_total_minor: int
    spending_total_minor: int
    net_total_minor: int


@dataclass(frozen=True, slots=True)
class RollingMeanPoint:
    date: date
    window_start: date
    window_end: date
    window_months: int
    income_mean_minor: int
    spending_mean_minor: int
    net_mean_minor: int


@dataclass(frozen=True, slots=True)
class RollingMeanSeries:
    month: tuple[RollingMeanPoint, ...]
    quarter: tuple[RollingMeanPoint, ...]
    year: tuple[RollingMeanPoint, ...]


@dataclass(frozen=True, slots=True)
class DashboardSeries:
    week: tuple[SeriesPoint, ...]
    month: tuple[SeriesPoint, ...]
    quarter: tuple[SeriesPoint, ...]
    rolling_mean: RollingMeanSeries


@dataclass(frozen=True, slots=True)
class MonthlyCompositionItem:
    period: str
    taxonomy_id: str
    name: str
    amount_minor: int
    count: int
    partial: bool


@dataclass(frozen=True, slots=True)
class RankedCompositionItem:
    taxonomy_id: str
    name: str
    amount_minor: int
    count: int
    percentage: float


@dataclass(frozen=True, slots=True)
class CompositionBreakdown:
    category_monthly: tuple[MonthlyCompositionItem, ...]
    subcategory_monthly: tuple[MonthlyCompositionItem, ...]
    category_ranked: tuple[RankedCompositionItem, ...]
    subcategory_ranked: tuple[RankedCompositionItem, ...]


@dataclass(frozen=True, slots=True)
class DashboardComposition:
    spending: CompositionBreakdown
    income: CompositionBreakdown


@dataclass(frozen=True, slots=True)
class AnnualMonth:
    month: int
    income_total_minor: int
    spending_total_minor: int
    net_total_minor: int


@dataclass(frozen=True, slots=True)
class AnnualPoint:
    year: int
    partial: bool
    income_total_minor: int
    spending_total_minor: int
    net_total_minor: int
    income_monthly_mean_minor: int
    spending_monthly_mean_minor: int
    net_monthly_mean_minor: int
    months: tuple[AnnualMonth, ...]


@dataclass(frozen=True, slots=True)
class CumulativePoint:
    date: date
    net_minor: int
    cumulative_minor: int


@dataclass(frozen=True, slots=True)
class RecentTransaction:
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


@dataclass(frozen=True, slots=True)
class DashboardQuality:
    transaction_count: int
    uncategorized_count: int
    category_only_count: int


@dataclass(frozen=True, slots=True)
class DashboardReport:
    meta: DashboardMeta
    summary: DashboardSummary
    series: DashboardSeries
    composition: DashboardComposition
    annual: tuple[AnnualPoint, ...]
    cumulative: tuple[CumulativePoint, ...]
    recent: tuple[RecentTransaction, ...]
    quality: DashboardQuality
