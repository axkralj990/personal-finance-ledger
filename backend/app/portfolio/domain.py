from dataclasses import dataclass
from datetime import date, datetime

from backend.app.database.models import AssetType, QuoteInterval, ValuationSource


@dataclass(frozen=True, slots=True)
class ManualValuationData:
    valued_at: date
    native_value_minor: int
    unit_price: str | None = None
    fx_rate_to_eur: str | None = None
    fx_rate_date: date | None = None
    fx_source: str | None = None
    fx_preview_token: str | None = None


@dataclass(frozen=True, slots=True)
class AssetCreateData:
    id: str | None
    name: str
    asset_type: AssetType
    currency: str
    acquisition_date: date
    quantity: str | None
    cost_basis_native_minor: int | None
    cost_basis_eur_minor: int | None
    cost_basis_fx_source: str | None
    cost_basis_fx_rate_to_eur: str | None
    cost_basis_fx_rate_date: date | None
    cost_basis_fx_preview_token: str | None
    quote_symbol: str | None
    quote_exchange: str | None
    quote_mic_code: str | None
    initial_valuation: ManualValuationData


@dataclass(frozen=True, slots=True)
class AssetPatchData:
    expected_revision: int
    changes: dict[str, object]
    effective_at: date | None
    replacement_valuation: ManualValuationData | None
    cost_basis_fx_preview_token: str | None
    archived_on: date | None


@dataclass(frozen=True, slots=True)
class QuoteSnapshotData:
    asset_id: str
    asset_revision: int
    source: ValuationSource
    quote_interval: QuoteInterval
    valued_at: date
    native_currency: str
    native_value_minor: int
    eur_value_minor: int
    quantity: str
    unit_price: str
    quote_symbol: str
    quote_exchange: str | None
    quote_mic_code: str | None
    quote_name: str
    quote_fetched_at: datetime
    fx_source: str
    fx_rate_to_eur: str
    fx_rate_date: date


@dataclass(frozen=True, slots=True)
class FxPreviewData:
    currency: str
    valued_at: date
    source: str
    rate_to_eur: str
    rate_date: date


@dataclass(frozen=True, slots=True)
class PortfolioHolding:
    asset_id: str
    name: str
    asset_type: AssetType
    currency: str
    revision: int
    quantity: str | None
    valuation_id: str | None
    valued_at: date | None
    source: ValuationSource | None
    native_value_minor: int | None
    eur_value_minor: int | None
    cost_basis_eur_minor: int | None
    unrealized_pnl_minor: int | None
    return_percent: str | None
    missing_valuation: bool


@dataclass(frozen=True, slots=True)
class AllocationItem:
    key: str
    name: str
    value_minor: int
    percentage: str | None


@dataclass(frozen=True, slots=True)
class AssetPnl:
    asset_id: str
    name: str
    cost_basis_eur_minor: int | None
    current_value_eur_minor: int | None
    unrealized_pnl_minor: int | None
    return_percent: str | None


@dataclass(frozen=True, slots=True)
class PortfolioHistoryPoint:
    date: date
    complete: bool
    known_value_minor: int
    total_value_minor: int | None
    tracked_cost_basis_minor: int | None
    unrealized_pnl_minor: int | None
    pnl_eligible_assets: int
    pnl_covered_assets: int


@dataclass(frozen=True, slots=True)
class PortfolioReport:
    as_of: date
    generated_at: datetime
    currency: str
    complete: bool
    missing_asset_ids: tuple[str, ...]
    asset_count: int
    valued_asset_count: int
    known_value_minor: int
    total_value_minor: int | None
    tracked_cost_basis_minor: int | None
    unrealized_pnl_minor: int | None
    return_percent: str | None
    pnl_eligible_assets: int
    pnl_covered_assets: int
    allocation_by_type: tuple[AllocationItem, ...]
    allocation_by_asset: tuple[AllocationItem, ...]
    pnl_by_asset: tuple[AssetPnl, ...]
    holdings: tuple[PortfolioHolding, ...]
    history: tuple[PortfolioHistoryPoint, ...]
