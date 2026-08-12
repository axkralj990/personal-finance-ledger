from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from backend.app.database.models import AssetType, QuoteInterval, ValuationSource
from backend.app.portfolio.domain import (
    AssetCreateData,
    ManualValuationData,
    QuoteSnapshotData,
)
from backend.app.portfolio.precision import DECIMAL_PATTERN, JS_SAFE_INTEGER

CanonicalDecimal = Annotated[
    str,
    StringConstraints(pattern=DECIMAL_PATTERN.pattern, max_length=80),
]
MoneyMinor = Annotated[int, Field(ge=0, le=JS_SAFE_INTEGER)]
SignedMoneyMinor = Annotated[int, Field(ge=-JS_SAFE_INTEGER, le=JS_SAFE_INTEGER)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuoteConfiguration(StrictModel):
    symbol: str = Field(min_length=1, max_length=40)
    exchange: str | None = Field(default=None, min_length=1, max_length=80)
    mic_code: str | None = Field(default=None, min_length=1, max_length=12)

    @field_validator("symbol", "exchange", "mic_code")
    @classmethod
    def normalize_identity(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None else None

    @model_validator(mode="after")
    def exchange_or_mic(self):
        if self.exchange is None and self.mic_code is None:
            raise ValueError("quote configuration requires exchange or mic_code")
        return self


class ManualValuationInput(StrictModel):
    valued_at: date
    native_value_minor: MoneyMinor
    unit_price: CanonicalDecimal | None = None
    fx_source: Literal["ECB", "MANUAL", "IDENTITY"] | None = None
    fx_rate_to_eur: CanonicalDecimal | None = None
    fx_rate_date: date | None = None
    fx_preview_token: str | None = Field(default=None, min_length=64, max_length=64)

    def to_domain(self) -> ManualValuationData:
        return ManualValuationData(
            valued_at=self.valued_at,
            native_value_minor=self.native_value_minor,
            unit_price=self.unit_price,
            fx_source=self.fx_source,
            fx_rate_to_eur=self.fx_rate_to_eur,
            fx_rate_date=self.fx_rate_date,
            fx_preview_token=self.fx_preview_token,
        )


class AssetCreate(StrictModel):
    id: UUID | None = None
    name: str = Field(min_length=1, max_length=160)
    asset_type: AssetType
    currency: str = Field(min_length=3, max_length=3)
    acquisition_date: date
    quantity: CanonicalDecimal | None = None
    cost_basis_native_minor: MoneyMinor | None = None
    cost_basis_eur_minor: MoneyMinor | None = None
    cost_basis_fx_source: Literal["ECB", "MANUAL", "IDENTITY"] | None = None
    cost_basis_fx_rate_to_eur: CanonicalDecimal | None = None
    cost_basis_fx_rate_date: date | None = None
    cost_basis_fx_preview_token: str | None = Field(default=None, min_length=64, max_length=64)
    quote: QuoteConfiguration | None = None
    initial_valuation: ManualValuationInput

    @field_validator("name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value

    @field_validator("currency")
    @classmethod
    def normalize_currency(cls, value: str) -> str:
        value = value.upper()
        if not value.isalpha():
            raise ValueError("currency must contain letters")
        return value

    def to_domain(self) -> AssetCreateData:
        return AssetCreateData(
            id=str(self.id) if self.id is not None else None,
            name=self.name,
            asset_type=self.asset_type,
            currency=self.currency,
            acquisition_date=self.acquisition_date,
            quantity=self.quantity,
            cost_basis_native_minor=self.cost_basis_native_minor,
            cost_basis_eur_minor=self.cost_basis_eur_minor,
            cost_basis_fx_source=self.cost_basis_fx_source,
            cost_basis_fx_rate_to_eur=self.cost_basis_fx_rate_to_eur,
            cost_basis_fx_rate_date=self.cost_basis_fx_rate_date,
            cost_basis_fx_preview_token=self.cost_basis_fx_preview_token,
            quote_symbol=self.quote.symbol if self.quote else None,
            quote_exchange=self.quote.exchange if self.quote else None,
            quote_mic_code=self.quote.mic_code if self.quote else None,
            initial_valuation=self.initial_valuation.to_domain(),
        )


class AssetPatch(StrictModel):
    expected_revision: int = Field(ge=1)
    name: str | None = Field(default=None, min_length=1, max_length=160)
    asset_type: AssetType | None = None
    quantity: CanonicalDecimal | None = None
    cost_basis_native_minor: MoneyMinor | None = None
    cost_basis_eur_minor: MoneyMinor | None = None
    cost_basis_fx_source: Literal["ECB", "MANUAL", "IDENTITY"] | None = None
    cost_basis_fx_rate_to_eur: CanonicalDecimal | None = None
    cost_basis_fx_rate_date: date | None = None
    cost_basis_fx_preview_token: str | None = Field(default=None, min_length=64, max_length=64)
    quote: QuoteConfiguration | None = None
    is_active: bool | None = None
    effective_at: date | None = None
    replacement_valuation: ManualValuationInput | None = None

    @model_validator(mode="before")
    @classmethod
    def reject_explicit_nulls(cls, value):
        if isinstance(value, dict):
            for field in ("name", "asset_type", "is_active"):
                if field in value and value[field] is None:
                    raise ValueError(f"{field} cannot be null")
        return value

    @field_validator("name")
    @classmethod
    def strip_optional_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("name cannot be blank")
        return value


class ManualValuationCreate(ManualValuationInput):
    expected_revision: int = Field(ge=1)


class ValuationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    asset_id: str
    valued_at: date
    native_value_minor: MoneyMinor
    eur_value_minor: MoneyMinor
    quantity: str | None
    unit_price: str | None
    cost_basis_native_minor: MoneyMinor | None
    cost_basis_eur_minor: MoneyMinor | None
    cost_basis_fx_source: str | None
    cost_basis_fx_rate_to_eur: str | None
    cost_basis_fx_rate_date: date | None
    source: ValuationSource
    quote_symbol: str | None
    quote_exchange: str | None
    quote_mic_code: str | None
    quote_name: str | None
    quote_fetched_at: datetime | None
    quote_interval: QuoteInterval | None
    fx_source: str
    fx_rate_to_eur: str
    fx_rate_date: date
    created_at: datetime

    @field_validator("quote_fetched_at", "created_at", mode="before")
    @classmethod
    def restore_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class AssetRead(BaseModel):
    id: str
    name: str
    asset_type: AssetType
    currency: str
    acquisition_date: date
    quantity: str | None
    cost_basis_native_minor: MoneyMinor | None
    cost_basis_eur_minor: MoneyMinor | None
    cost_basis_fx_source: str | None
    cost_basis_fx_rate_to_eur: str | None
    cost_basis_fx_rate_date: date | None
    quote: QuoteConfiguration | None
    is_active: bool
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    archived_on: date | None
    latest_valuation: ValuationRead | None

    @field_validator("created_at", "updated_at", "archived_at", mode="before")
    @classmethod
    def restore_utc(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class QuoteDetails(StrictModel):
    symbol: str = Field(min_length=1, max_length=40)
    exchange: str | None = Field(default=None, min_length=1, max_length=80)
    mic_code: str | None = Field(default=None, min_length=1, max_length=12)
    name: str = Field(min_length=1, max_length=200)
    fetched_at: datetime

    @field_validator("fetched_at")
    @classmethod
    def timezone_required(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("fetched_at must include a timezone")
        return value


class FxDetails(StrictModel):
    source: Literal["ECB", "IDENTITY"]
    rate_to_eur: CanonicalDecimal
    rate_date: date


class FxPreviewRead(StrictModel):
    currency: str
    valued_at: date
    source: Literal["ECB", "IDENTITY"]
    rate_to_eur: CanonicalDecimal
    rate_date: date
    preview_token: str = Field(min_length=64, max_length=64)


class QuotePreviewReady(StrictModel):
    status: Literal["ready"] = "ready"
    asset_id: str
    asset_revision: int = Field(ge=1)
    source: Literal["TWELVE_DATA", "YAHOO_FINANCE"]
    quote_interval: Literal["LIVE", "MONTHLY"] = "LIVE"
    valued_at: date
    native_currency: str = Field(min_length=3, max_length=3)
    native_value_minor: MoneyMinor
    eur_value_minor: MoneyMinor
    quantity: CanonicalDecimal
    unit_price: CanonicalDecimal
    quote: QuoteDetails
    fx: FxDetails
    preview_token: str = Field(min_length=64, max_length=64)

    def to_domain(self) -> QuoteSnapshotData:
        return QuoteSnapshotData(
            asset_id=self.asset_id,
            asset_revision=self.asset_revision,
            source=ValuationSource(self.source),
            quote_interval=QuoteInterval(self.quote_interval),
            valued_at=self.valued_at,
            native_currency=self.native_currency,
            native_value_minor=self.native_value_minor,
            eur_value_minor=self.eur_value_minor,
            quantity=self.quantity,
            unit_price=self.unit_price,
            quote_symbol=self.quote.symbol,
            quote_exchange=self.quote.exchange,
            quote_mic_code=self.quote.mic_code,
            quote_name=self.quote.name,
            quote_fetched_at=self.quote.fetched_at,
            fx_source=self.fx.source,
            fx_rate_to_eur=self.fx.rate_to_eur,
            fx_rate_date=self.fx.rate_date,
        )

    @classmethod
    def from_domain(cls, snapshot: QuoteSnapshotData, preview_token: str) -> QuotePreviewReady:
        return cls(
            asset_id=snapshot.asset_id,
            asset_revision=snapshot.asset_revision,
            source=snapshot.source.value,
            quote_interval=snapshot.quote_interval.value,
            valued_at=snapshot.valued_at,
            native_currency=snapshot.native_currency,
            native_value_minor=snapshot.native_value_minor,
            eur_value_minor=snapshot.eur_value_minor,
            quantity=snapshot.quantity,
            unit_price=snapshot.unit_price,
            quote=QuoteDetails(
                symbol=snapshot.quote_symbol,
                exchange=snapshot.quote_exchange,
                mic_code=snapshot.quote_mic_code,
                name=snapshot.quote_name,
                fetched_at=snapshot.quote_fetched_at,
            ),
            fx=FxDetails(
                source=snapshot.fx_source,
                rate_to_eur=snapshot.fx_rate_to_eur,
                rate_date=snapshot.fx_rate_date,
            ),
            preview_token=preview_token,
        )


class QuoteError(StrictModel):
    code: str
    message: str
    recoverable: bool


class QuotePreviewError(StrictModel):
    status: Literal["error"] = "error"
    asset_id: str
    asset_revision: int | None = None
    error: QuoteError


QuotePreviewItem = Annotated[QuotePreviewReady | QuotePreviewError, Field(discriminator="status")]


class QuotePreviewResponse(StrictModel):
    items: list[QuotePreviewItem]


class QuoteHistoryPreviewRead(StrictModel):
    asset_id: str
    asset_revision: int = Field(ge=1)
    source: Literal["YAHOO_FINANCE"] = "YAHOO_FINANCE"
    available_months: int = Field(ge=0)
    existing_months: int = Field(ge=0)
    first_date: date | None
    last_date: date | None
    items: list[QuotePreviewReady]


class QuoteSnapshotsCreate(StrictModel):
    items: list[QuotePreviewReady] = Field(min_length=1)


class QuoteSnapshotsRead(StrictModel):
    items: list[ValuationRead]


class DomainRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AllocationRead(DomainRead):
    key: str
    name: str
    value_minor: MoneyMinor
    percentage: str | None


class AssetPnlRead(DomainRead):
    asset_id: str
    name: str
    cost_basis_eur_minor: MoneyMinor | None
    current_value_eur_minor: MoneyMinor | None
    unrealized_pnl_minor: SignedMoneyMinor | None
    return_percent: str | None


class PortfolioHoldingRead(DomainRead):
    asset_id: str
    name: str
    asset_type: AssetType
    currency: str
    revision: int
    quantity: str | None
    valuation_id: str | None
    valued_at: date | None
    source: ValuationSource | None
    native_value_minor: MoneyMinor | None
    eur_value_minor: MoneyMinor | None
    cost_basis_eur_minor: MoneyMinor | None
    unrealized_pnl_minor: SignedMoneyMinor | None
    return_percent: str | None
    missing_valuation: bool


class PortfolioHistoryRead(DomainRead):
    date: date
    complete: bool
    known_value_minor: MoneyMinor
    total_value_minor: MoneyMinor | None
    tracked_cost_basis_minor: MoneyMinor | None
    unrealized_pnl_minor: SignedMoneyMinor | None
    pnl_eligible_assets: int
    pnl_covered_assets: int


class PortfolioRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    as_of: date
    generated_at: datetime
    currency: Literal["EUR"]
    complete: bool
    missing_asset_ids: tuple[str, ...]
    asset_count: int
    valued_asset_count: int
    known_value_minor: MoneyMinor
    total_value_minor: MoneyMinor | None
    tracked_cost_basis_minor: MoneyMinor | None
    unrealized_pnl_minor: SignedMoneyMinor | None
    return_percent: str | None
    pnl_eligible_assets: int
    pnl_covered_assets: int
    allocation_by_type: tuple[AllocationRead, ...]
    allocation_by_asset: tuple[AllocationRead, ...]
    pnl_by_asset: tuple[AssetPnlRead, ...]
    holdings: tuple[PortfolioHoldingRead, ...]
    history: tuple[PortfolioHistoryRead, ...]
