from __future__ import annotations

from calendar import monthrange
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.database.models import (
    Asset,
    AssetEvent,
    AssetType,
    AssetValuation,
    ValuationSource,
    utc_now,
)
from backend.app.portfolio.domain import (
    AllocationItem,
    AssetCreateData,
    AssetPatchData,
    AssetPnl,
    ManualValuationData,
    PortfolioHistoryPoint,
    PortfolioHolding,
    PortfolioReport,
    QuoteSnapshotData,
)
from backend.app.portfolio.precision import (
    SUPPORTED_PORTFOLIO_CURRENCIES,
    checked_minor_sum,
    convert_minor_to_eur,
    parse_decimal,
    percentage,
    position_value_minor,
)
from backend.app.problems import Problem

REPORTING_CURRENCY = "EUR"
CASH_TYPES = {AssetType.BANK_CASH, AssetType.BROKERAGE_CASH}
SECURITY_TYPES = {AssetType.ETF, AssetType.STOCK}
POSITION_FIELDS = {
    "quantity",
    "cost_basis_native_minor",
    "cost_basis_eur_minor",
    "cost_basis_fx_source",
    "cost_basis_fx_rate_to_eur",
    "cost_basis_fx_rate_date",
}


@dataclass(frozen=True, slots=True)
class _Position:
    quantity: str | None
    cost_basis_native_minor: int | None
    cost_basis_eur_minor: int | None
    cost_basis_fx_source: str | None
    cost_basis_fx_rate_to_eur: str | None
    cost_basis_fx_rate_date: date | None


def list_assets(session: Session, *, include_archived: bool = False) -> list[Asset]:
    statement = select(Asset)
    if not include_archived:
        statement = statement.where(Asset.is_active.is_(True))
    return list(session.scalars(statement.order_by(Asset.name, Asset.id)))


def get_asset(session: Session, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None:
        raise Problem(404, "asset_not_found", "Asset was not found")
    return asset


def list_valuations(session: Session, asset_id: str) -> list[AssetValuation]:
    get_asset(session, asset_id)
    return list(
        session.scalars(
            select(AssetValuation)
            .where(AssetValuation.asset_id == asset_id)
            .order_by(
                AssetValuation.valued_at.desc(),
                AssetValuation.created_at.desc(),
                AssetValuation.id.desc(),
            )
        )
    )


def latest_valuation(
    session: Session, asset_id: str, *, as_of: date | None = None
) -> AssetValuation | None:
    statement = select(AssetValuation).where(AssetValuation.asset_id == asset_id)
    if as_of is not None:
        statement = statement.where(AssetValuation.valued_at <= as_of)
    return session.scalar(
        statement.order_by(
            AssetValuation.valued_at.desc(),
            AssetValuation.created_at.desc(),
            AssetValuation.id.desc(),
        ).limit(1)
    )


def create_asset(session: Session, data: AssetCreateData) -> Asset:
    _validate_asset_state(data)
    asset = Asset(
        name=data.name.strip(),
        asset_type=data.asset_type,
        currency=data.currency,
        acquisition_date=data.acquisition_date,
        quantity=data.quantity,
        cost_basis_native_minor=data.cost_basis_native_minor,
        cost_basis_eur_minor=data.cost_basis_eur_minor,
        cost_basis_fx_source=data.cost_basis_fx_source,
        cost_basis_fx_rate_to_eur=data.cost_basis_fx_rate_to_eur,
        cost_basis_fx_rate_date=data.cost_basis_fx_rate_date,
        quote_symbol=data.quote_symbol,
        quote_exchange=data.quote_exchange,
        quote_mic_code=data.quote_mic_code,
    )
    if data.id is not None:
        asset.id = data.id
    session.add(asset)
    session.flush()
    session.add(_manual_valuation(asset, data.initial_valuation, _current_position(asset)))
    session.commit()
    return asset


def patch_asset(session: Session, asset_id: str, data: AssetPatchData) -> Asset:
    asset = get_asset(session, asset_id)
    _require_active(asset)
    _check_revision(asset, data.expected_revision)
    changes = dict(data.changes)
    if not changes:
        raise Problem(422, "empty_patch", "At least one asset field must be changed")

    position_changed = bool(POSITION_FIELDS & changes.keys())
    if position_changed and (data.effective_at is None or data.replacement_valuation is None):
        raise Problem(
            422,
            "replacement_valuation_required",
            "Position changes require effective_at and replacement_valuation",
            recoverable=True,
        )
    if position_changed:
        current_valuation = latest_valuation(session, asset.id)
        if current_valuation is not None and data.effective_at < current_valuation.valued_at:
            raise Problem(
                422,
                "position_date_before_latest_valuation",
                "Position effective_at cannot precede the latest valuation",
                field="effective_at",
                recoverable=True,
            )
    if not position_changed and (data.effective_at or data.replacement_valuation):
        raise Problem(
            422,
            "unexpected_replacement_valuation",
            "Replacement valuation is only valid with quantity or cost basis changes",
            recoverable=True,
        )

    previous = {field: _json_value(getattr(asset, field)) for field in changes}
    for field, value in changes.items():
        setattr(asset, field, value)
    cost_effective_date = (
        data.effective_at
        or asset.cost_basis_fx_rate_date
        or asset.acquisition_date
    )
    _validate_asset_model(asset, cost_effective_date)

    if position_changed:
        if data.replacement_valuation.valued_at != data.effective_at:
            raise Problem(
                422,
                "effective_date_mismatch",
                "Replacement valuation date must equal effective_at",
                field="replacement_valuation.valued_at",
                recoverable=True,
            )
        session.add(_manual_valuation(asset, data.replacement_valuation, _current_position(asset)))

    now = utc_now()
    event_type = "ARCHIVED" if changes.get("is_active") is False else "CORRECTION"
    event_values = {field: _json_value(value) for field, value in changes.items()}
    if event_type == "ARCHIVED":
        if data.archived_on is None:
            raise Problem(422, "archive_date_required", "Archive date is required")
        asset.archived_at = now
        asset.archived_on = data.archived_on
        event_values["archived_on"] = data.archived_on.isoformat()
    previous_revision = asset.revision
    asset.revision += 1
    asset.updated_at = now
    session.add(
        AssetEvent(
            asset_id=asset.id,
            event_type=event_type,
            previous_revision=previous_revision,
            new_revision=asset.revision,
            effective_at=data.effective_at,
            previous_values=previous,
            new_values=event_values,
        )
    )
    session.commit()
    return asset


def add_manual_valuation(
    session: Session, asset_id: str, data: ManualValuationData, expected_revision: int
) -> AssetValuation:
    asset = get_asset(session, asset_id)
    _require_active(asset)
    _check_revision(asset, expected_revision)
    valuation = _manual_valuation(asset, data, _position_at(session, asset, data.valued_at))
    session.add(valuation)
    session.commit()
    return valuation


def persist_quote_snapshots(
    session: Session,
    snapshots: tuple[QuoteSnapshotData, ...],
    *,
    max_age_hours: int,
) -> list[AssetValuation]:
    if not snapshots:
        raise Problem(422, "empty_quote_snapshots", "At least one quote snapshot is required")
    request_keys = {
        (
            snapshot.asset_id,
            snapshot.source,
            _as_utc(snapshot.quote_fetched_at),
            snapshot.valued_at,
        )
        for snapshot in snapshots
    }
    if len(request_keys) != len(snapshots):
        raise Problem(
            422,
            "duplicate_quote_snapshot",
            "Quote snapshot request contains a duplicate provider date",
        )

    valuations: list[AssetValuation] = []
    now = datetime.now(UTC)
    for snapshot in snapshots:
        asset = get_asset(session, snapshot.asset_id)
        _require_active(asset)
        _check_revision(asset, snapshot.asset_revision)
        _validate_quote_snapshot(asset, snapshot)
        fetched_at = _as_utc(snapshot.quote_fetched_at)
        if now - fetched_at > timedelta(hours=max_age_hours):
            raise Problem(
                409,
                "quote_preview_expired",
                "Quote preview is too old to persist",
                recoverable=True,
            )
        exact_replay = session.scalar(
            select(AssetValuation.id).where(
                AssetValuation.asset_id == asset.id,
                AssetValuation.source == snapshot.source,
                AssetValuation.quote_fetched_at == fetched_at,
                AssetValuation.valued_at == snapshot.valued_at,
            )
        )
        if exact_replay is not None:
            raise Problem(
                409,
                "quote_preview_replayed",
                "Quote preview was already persisted",
                recoverable=True,
            )
        latest_fetched_at = session.scalar(
            select(AssetValuation.quote_fetched_at)
            .where(
                AssetValuation.asset_id == asset.id,
                AssetValuation.source != ValuationSource.MANUAL,
            )
            .order_by(AssetValuation.quote_fetched_at.desc())
            .limit(1)
        )
        if latest_fetched_at is not None:
            latest_utc = _as_utc(latest_fetched_at)
            if fetched_at < latest_utc:
                raise Problem(
                    409,
                    "quote_snapshot_not_newer",
                    "Quote preview is older than the latest persisted quote",
                    recoverable=True,
                )
        valuations.append(
            AssetValuation(
                asset_id=asset.id,
                valued_at=snapshot.valued_at,
                native_value_minor=snapshot.native_value_minor,
                eur_value_minor=snapshot.eur_value_minor,
                quantity=snapshot.quantity,
                unit_price=snapshot.unit_price,
                cost_basis_native_minor=asset.cost_basis_native_minor,
                cost_basis_eur_minor=asset.cost_basis_eur_minor,
                cost_basis_fx_source=asset.cost_basis_fx_source,
                cost_basis_fx_rate_to_eur=asset.cost_basis_fx_rate_to_eur,
                cost_basis_fx_rate_date=asset.cost_basis_fx_rate_date,
                source=snapshot.source,
                quote_symbol=snapshot.quote_symbol,
                quote_exchange=snapshot.quote_exchange,
                quote_mic_code=snapshot.quote_mic_code,
                quote_name=snapshot.quote_name,
                quote_fetched_at=fetched_at,
                quote_interval=snapshot.quote_interval,
                fx_source=snapshot.fx_source,
                fx_rate_to_eur=snapshot.fx_rate_to_eur,
                fx_rate_date=snapshot.fx_rate_date,
            )
        )
    session.add_all(valuations)
    try:
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        raise Problem(
            409,
            "quote_preview_replayed",
            "Quote preview was already persisted",
            recoverable=True,
        ) from exc
    return valuations


def build_portfolio(session: Session, as_of: date) -> PortfolioReport:
    assets = list(
        session.scalars(
            select(Asset).where(Asset.acquisition_date <= as_of).order_by(Asset.name, Asset.id)
        )
    )
    valuations = _load_valuations(session, assets, as_of)
    current_assets = [asset for asset in assets if _held_on(asset, as_of)]
    latest = _latest_by_asset(valuations)
    holdings = tuple(_holding(asset, latest.get(asset.id)) for asset in current_assets)
    missing_ids = tuple(holding.asset_id for holding in holdings if holding.missing_valuation)
    known_value = checked_minor_sum(holding.eur_value_minor or 0 for holding in holdings)
    pnl_items = tuple(
        _pnl_item(asset, latest.get(asset.id))
        for asset in current_assets
        if asset.asset_type not in CASH_TYPES
    )
    covered_pnl = [item for item in pnl_items if item.unrealized_pnl_minor is not None]
    tracked_cost = (
        checked_minor_sum(item.cost_basis_eur_minor or 0 for item in covered_pnl)
        if covered_pnl
        else None
    )
    unrealized_pnl = (
        checked_minor_sum(item.unrealized_pnl_minor or 0 for item in covered_pnl)
        if covered_pnl
        else None
    )
    complete = not missing_ids
    return PortfolioReport(
        as_of=as_of,
        generated_at=datetime.now(UTC),
        currency=REPORTING_CURRENCY,
        complete=complete,
        missing_asset_ids=missing_ids,
        asset_count=len(current_assets),
        valued_asset_count=len(current_assets) - len(missing_ids),
        known_value_minor=known_value,
        total_value_minor=known_value if complete else None,
        tracked_cost_basis_minor=tracked_cost,
        unrealized_pnl_minor=unrealized_pnl,
        return_percent=(
            percentage(unrealized_pnl, tracked_cost)
            if unrealized_pnl is not None and tracked_cost is not None
            else None
        ),
        pnl_eligible_assets=len(pnl_items),
        pnl_covered_assets=len(covered_pnl),
        allocation_by_type=_allocation_by_type(holdings, known_value),
        allocation_by_asset=_allocation_by_asset(holdings, known_value),
        pnl_by_asset=pnl_items,
        holdings=holdings,
        history=_history(assets, valuations, as_of),
    )


def _manual_valuation(
    asset: Asset, data: ManualValuationData, position: _Position
) -> AssetValuation:
    if data.valued_at < asset.acquisition_date:
        raise Problem(
            422,
            "valuation_before_acquisition",
            "Valuation date cannot be before asset acquisition",
            field="valued_at",
            recoverable=True,
        )
    rate, source, rate_date = _manual_fx(asset.currency, data)
    if data.unit_price is not None:
        unit_price = parse_decimal(data.unit_price, "unit_price", positive=True)
        if position.quantity is None:
            raise Problem(422, "quantity_required", "Unit price requires an asset quantity")
        quantity = parse_decimal(position.quantity, "quantity", positive=True)
        if position_value_minor(quantity, unit_price) != data.native_value_minor:
            raise Problem(
                422,
                "valuation_mismatch",
                "native_value_minor does not match quantity and unit_price",
                field="native_value_minor",
                recoverable=True,
            )
    return AssetValuation(
        asset_id=asset.id,
        valued_at=data.valued_at,
        native_value_minor=data.native_value_minor,
        eur_value_minor=convert_minor_to_eur(data.native_value_minor, rate),
        quantity=position.quantity,
        unit_price=data.unit_price,
        cost_basis_native_minor=position.cost_basis_native_minor,
        cost_basis_eur_minor=position.cost_basis_eur_minor,
        cost_basis_fx_source=position.cost_basis_fx_source,
        cost_basis_fx_rate_to_eur=position.cost_basis_fx_rate_to_eur,
        cost_basis_fx_rate_date=position.cost_basis_fx_rate_date,
        source=ValuationSource.MANUAL,
        fx_source=source,
        fx_rate_to_eur=str(rate),
        fx_rate_date=rate_date,
    )


def _manual_fx(currency: str, data: ManualValuationData) -> tuple[Decimal, str, date]:
    if currency == REPORTING_CURRENCY:
        fx_values = (data.fx_rate_to_eur, data.fx_source, data.fx_rate_date)
        if any(value is not None for value in fx_values) and fx_values != (
            "1",
            "IDENTITY",
            data.valued_at,
        ):
            raise Problem(
                422,
                "invalid_eur_fx",
                "EUR valuations use the identity FX rate",
                field="fx_rate_to_eur",
            )
        return parse_decimal("1", "fx_rate_to_eur", positive=True), "IDENTITY", data.valued_at
    if (
        data.fx_rate_to_eur is None
        or data.fx_rate_date is None
        or data.fx_source not in {"ECB", "MANUAL"}
    ):
        raise Problem(
            422,
            "manual_fx_required",
            "Non-EUR manual valuations require a manual FX rate and rate date",
            field="fx_rate_to_eur",
            recoverable=True,
        )
    if data.fx_rate_date > data.valued_at:
        raise Problem(
            422,
            "invalid_fx_date",
            "FX rate date cannot be after valuation date",
            field="fx_rate_date",
        )
    return (
        parse_decimal(data.fx_rate_to_eur, "fx_rate_to_eur", positive=True),
        data.fx_source,
        data.fx_rate_date,
    )


def _validate_asset_state(data: AssetCreateData) -> None:
    state = {
        "name": data.name,
        "asset_type": data.asset_type,
        "currency": data.currency,
        "quantity": data.quantity,
        "cost_basis_native_minor": data.cost_basis_native_minor,
        "cost_basis_eur_minor": data.cost_basis_eur_minor,
        "cost_basis_fx_source": data.cost_basis_fx_source,
        "cost_basis_fx_rate_to_eur": data.cost_basis_fx_rate_to_eur,
        "cost_basis_fx_rate_date": data.cost_basis_fx_rate_date,
        "quote_symbol": data.quote_symbol,
        "quote_exchange": data.quote_exchange,
        "quote_mic_code": data.quote_mic_code,
        "acquisition_date": data.acquisition_date,
    }
    _validate_state_values(state, data.acquisition_date)


def _validate_asset_model(asset: Asset, cost_effective_date: date) -> None:
    _validate_state_values(
        {
            "name": asset.name,
            "asset_type": asset.asset_type,
            "currency": asset.currency,
            "quantity": asset.quantity,
            "cost_basis_native_minor": asset.cost_basis_native_minor,
            "cost_basis_eur_minor": asset.cost_basis_eur_minor,
            "cost_basis_fx_source": asset.cost_basis_fx_source,
            "cost_basis_fx_rate_to_eur": asset.cost_basis_fx_rate_to_eur,
            "cost_basis_fx_rate_date": asset.cost_basis_fx_rate_date,
            "quote_symbol": asset.quote_symbol,
            "quote_exchange": asset.quote_exchange,
            "quote_mic_code": asset.quote_mic_code,
            "acquisition_date": asset.acquisition_date,
        },
        cost_effective_date,
    )


def _validate_state_values(state: dict[str, Any], cost_effective_date: date) -> None:
    if not str(state["name"]).strip():
        raise Problem(422, "invalid_asset_name", "Asset name cannot be blank", field="name")
    currency = str(state["currency"])
    if len(currency) != 3 or not currency.isalpha() or currency != currency.upper():
        raise Problem(422, "invalid_currency", "Currency must be an uppercase ISO code")
    if currency not in SUPPORTED_PORTFOLIO_CURRENCIES:
        raise Problem(
            422,
            "unsupported_portfolio_currency",
            "Currency is not supported by portfolio v1",
            field="currency",
            recoverable=True,
        )
    quantity = state["quantity"]
    if quantity is not None:
        parse_decimal(str(quantity), "quantity", positive=True)
    native_cost = state["cost_basis_native_minor"]
    eur_cost = state["cost_basis_eur_minor"]
    cost_values = (
        native_cost,
        eur_cost,
        state["cost_basis_fx_source"],
        state["cost_basis_fx_rate_to_eur"],
        state["cost_basis_fx_rate_date"],
    )
    if any(value is None for value in cost_values) and any(
        value is not None for value in cost_values
    ):
        raise Problem(
            422,
            "incomplete_cost_basis",
            "Cost basis money and FX provenance must be provided together",
            field="cost_basis_native_minor",
        )
    asset_type = state["asset_type"]
    if asset_type in CASH_TYPES and native_cost is not None:
        raise Problem(422, "cash_has_no_pnl", "Cash assets cannot have a tracked cost basis")
    if native_cost is not None:
        _validate_cost_basis(state, currency, cost_effective_date)
    quote_values = (state["quote_symbol"], state["quote_exchange"], state["quote_mic_code"])
    if any(value is not None for value in quote_values):
        if asset_type not in SECURITY_TYPES or not quote_values[0] or not any(quote_values[1:]):
            raise Problem(
                422,
                "invalid_quote_configuration",
                "ETF or stock quote configuration requires a symbol and exchange or MIC",
                field="quote",
            )
        if quantity is None:
            raise Problem(
                422,
                "quantity_required",
                "Quoted assets require a quantity",
                field="quantity",
            )


def _validate_cost_basis(state: dict[str, Any], currency: str, cost_effective_date: date) -> None:
    native_cost = int(state["cost_basis_native_minor"])
    eur_cost = int(state["cost_basis_eur_minor"])
    source = str(state["cost_basis_fx_source"])
    rate_text = str(state["cost_basis_fx_rate_to_eur"])
    rate_date = state["cost_basis_fx_rate_date"]
    rate = parse_decimal(rate_text, "cost_basis_fx_rate_to_eur", positive=True)
    if rate_date > cost_effective_date:
        raise Problem(
            422,
            "invalid_cost_basis_fx_date",
            "Cost basis FX date cannot follow its effective date",
            field="cost_basis_fx_rate_date",
        )
    if currency == REPORTING_CURRENCY:
        if source != "IDENTITY" or rate_text != "1" or native_cost != eur_cost:
            raise Problem(
                422,
                "invalid_eur_cost_basis",
                "EUR cost basis requires identity FX and equal native and EUR values",
                field="cost_basis_fx_source",
            )
    elif source not in {"ECB", "MANUAL"}:
        raise Problem(
            422,
            "invalid_cost_basis_fx_source",
            "Non-EUR cost basis requires ECB or MANUAL FX provenance",
            field="cost_basis_fx_source",
        )
    if convert_minor_to_eur(native_cost, rate) != eur_cost:
        raise Problem(
            422,
            "cost_basis_fx_mismatch",
            "EUR cost basis does not match native cost and FX rate",
            field="cost_basis_eur_minor",
        )


def _validate_quote_snapshot(asset: Asset, snapshot: QuoteSnapshotData) -> None:
    if (
        asset.asset_type not in SECURITY_TYPES
        or asset.quote_symbol is None
        or asset.quantity is None
    ):
        raise Problem(422, "quote_not_configured", "Asset is not configured for market quotes")
    expected_config = (asset.quote_symbol, asset.quote_exchange, asset.quote_mic_code)
    submitted_config = (
        snapshot.quote_symbol,
        snapshot.quote_exchange,
        snapshot.quote_mic_code,
    )
    if expected_config != submitted_config or snapshot.native_currency != asset.currency:
        raise Problem(
            409,
            "quote_configuration_changed",
            "Asset quote configuration changed since preview",
            recoverable=True,
        )
    if snapshot.valued_at > date.today():
        raise Problem(422, "quote_from_future", "Quote date cannot be in the future")
    if snapshot.valued_at < asset.acquisition_date:
        raise Problem(422, "quote_before_acquisition", "Quote date precedes asset acquisition")
    if snapshot.quantity != asset.quantity:
        raise Problem(
            409,
            "position_changed",
            "Asset quantity changed since preview",
            recoverable=True,
        )
    quantity = parse_decimal(snapshot.quantity, "quantity", positive=True)
    unit_price = parse_decimal(snapshot.unit_price, "unit_price", positive=True)
    if position_value_minor(quantity, unit_price) != snapshot.native_value_minor:
        raise Problem(422, "quote_value_mismatch", "Quote value does not match quantity and price")
    rate = parse_decimal(snapshot.fx_rate_to_eur, "fx.rate_to_eur", positive=True)
    if convert_minor_to_eur(snapshot.native_value_minor, rate) != snapshot.eur_value_minor:
        raise Problem(422, "fx_value_mismatch", "EUR value does not match quote value and FX rate")
    if asset.currency == REPORTING_CURRENCY:
        if (
            snapshot.fx_source != "IDENTITY"
            or snapshot.fx_rate_to_eur != "1"
            or snapshot.fx_rate_date != snapshot.valued_at
        ):
            raise Problem(422, "invalid_eur_fx", "EUR quotes must use identity FX")
    elif snapshot.fx_source != "ECB" or snapshot.fx_rate_date > snapshot.valued_at:
        raise Problem(422, "invalid_quote_fx", "Non-EUR quotes require a prior ECB FX rate")


def _load_valuations(session: Session, assets: list[Asset], as_of: date) -> list[AssetValuation]:
    asset_ids = [asset.id for asset in assets]
    if not asset_ids:
        return []
    return list(
        session.scalars(
            select(AssetValuation)
            .where(
                AssetValuation.asset_id.in_(asset_ids),
                AssetValuation.valued_at <= as_of,
            )
            .order_by(
                AssetValuation.asset_id,
                AssetValuation.valued_at,
                AssetValuation.created_at,
                AssetValuation.id,
            )
        )
    )


def _latest_by_asset(valuations: list[AssetValuation]) -> dict[str, AssetValuation]:
    latest: dict[str, AssetValuation] = {}
    for valuation in valuations:
        latest[valuation.asset_id] = valuation
    return latest


def _holding(asset: Asset, valuation: AssetValuation | None) -> PortfolioHolding:
    tracks_pnl = asset.asset_type not in CASH_TYPES
    has_market_value = valuation is not None and not _is_unpriced_security(asset, valuation)
    pnl = None
    return_value = None
    if has_market_value and tracks_pnl and valuation.cost_basis_eur_minor is not None:
        pnl = valuation.eur_value_minor - valuation.cost_basis_eur_minor
        return_value = percentage(pnl, valuation.cost_basis_eur_minor)
    return PortfolioHolding(
        asset_id=asset.id,
        name=asset.name,
        asset_type=asset.asset_type,
        currency=asset.currency,
        revision=asset.revision,
        quantity=valuation.quantity if valuation else None,
        valuation_id=valuation.id if valuation else None,
        valued_at=valuation.valued_at if valuation else None,
        source=valuation.source if valuation else None,
        native_value_minor=valuation.native_value_minor if valuation else None,
        eur_value_minor=valuation.eur_value_minor if valuation else None,
        cost_basis_eur_minor=(valuation.cost_basis_eur_minor if tracks_pnl and valuation else None),
        unrealized_pnl_minor=pnl,
        return_percent=return_value,
        missing_valuation=valuation is None,
    )


def _pnl_item(asset: Asset, valuation: AssetValuation | None) -> AssetPnl:
    cost = valuation.cost_basis_eur_minor if valuation else None
    value = (
        valuation.eur_value_minor
        if valuation is not None and not _is_unpriced_security(asset, valuation)
        else None
    )
    pnl = value - cost if value is not None and cost is not None else None
    return AssetPnl(
        asset_id=asset.id,
        name=asset.name,
        cost_basis_eur_minor=cost,
        current_value_eur_minor=value,
        unrealized_pnl_minor=pnl,
        return_percent=percentage(pnl, cost) if pnl is not None and cost is not None else None,
    )


def _is_unpriced_security(asset: Asset, valuation: AssetValuation) -> bool:
    return (
        asset.asset_type in SECURITY_TYPES
        and asset.quote_symbol is not None
        and valuation.source == ValuationSource.MANUAL
        and valuation.quote_fetched_at is None
        and valuation.cost_basis_native_minor is not None
        and valuation.native_value_minor == valuation.cost_basis_native_minor
    )


def _allocation_by_type(
    holdings: tuple[PortfolioHolding, ...], known_total: int
) -> tuple[AllocationItem, ...]:
    totals: defaultdict[AssetType, int] = defaultdict(int)
    for holding in holdings:
        if holding.eur_value_minor is not None:
            totals[holding.asset_type] = checked_minor_sum(
                (totals[holding.asset_type], holding.eur_value_minor)
            )
    return tuple(
        AllocationItem(
            key=asset_type.value,
            name=asset_type.value.replace("_", " ").title(),
            value_minor=value,
            percentage=percentage(value, known_total),
        )
        for asset_type, value in sorted(totals.items(), key=lambda item: (-item[1], item[0].value))
    )


def _allocation_by_asset(
    holdings: tuple[PortfolioHolding, ...], known_total: int
) -> tuple[AllocationItem, ...]:
    valued = [holding for holding in holdings if holding.eur_value_minor is not None]
    valued.sort(
        key=lambda item: (-(item.eur_value_minor or 0), item.name.casefold(), item.asset_id)
    )
    return tuple(
        AllocationItem(
            key=holding.asset_id,
            name=holding.name,
            value_minor=holding.eur_value_minor or 0,
            percentage=percentage(holding.eur_value_minor or 0, known_total),
        )
        for holding in valued
    )


def _history(
    assets: list[Asset], valuations: list[AssetValuation], as_of: date
) -> tuple[PortfolioHistoryPoint, ...]:
    if not assets:
        return ()
    by_asset: defaultdict[str, list[AssetValuation]] = defaultdict(list)
    for valuation in valuations:
        by_asset[valuation.asset_id].append(valuation)
    point_dates: list[date] = []
    point = _month_end(min(asset.acquisition_date for asset in assets))
    last_point = _month_end(as_of)
    if last_point > as_of:
        last_point = _previous_month_end(as_of)
    while point <= last_point:
        point_dates.append(point)
        point = _month_end(_next_month(point))
    if not point_dates or point_dates[-1] != as_of:
        point_dates.append(as_of)

    points: list[PortfolioHistoryPoint] = []
    for point in point_dates:
        eligible = [asset for asset in assets if _held_on(asset, point)]
        current = {asset.id: _latest_before(by_asset[asset.id], point) for asset in eligible}
        known = checked_minor_sum(
            item.eur_value_minor for item in current.values() if item is not None
        )
        complete = all(item is not None for item in current.values())
        pnl_assets = [asset for asset in eligible if asset.asset_type not in CASH_TYPES]
        pnl_values = [
            current[asset.id]
            for asset in pnl_assets
            if current[asset.id] is not None
            and current[asset.id].cost_basis_eur_minor is not None
            and not _is_unpriced_security(asset, current[asset.id])
        ]
        tracked_cost = (
            checked_minor_sum(item.cost_basis_eur_minor or 0 for item in pnl_values)
            if pnl_values
            else None
        )
        pnl = (
            checked_minor_sum(
                item.eur_value_minor - (item.cost_basis_eur_minor or 0) for item in pnl_values
            )
            if pnl_values
            else None
        )
        points.append(
            PortfolioHistoryPoint(
                date=point,
                complete=complete,
                known_value_minor=known,
                total_value_minor=known if complete else None,
                tracked_cost_basis_minor=tracked_cost,
                unrealized_pnl_minor=pnl,
                pnl_eligible_assets=len(pnl_assets),
                pnl_covered_assets=len(pnl_values),
            )
        )
    return tuple(points)


def _latest_before(valuations: list[AssetValuation], point: date) -> AssetValuation | None:
    latest = None
    for valuation in valuations:
        if valuation.valued_at > point:
            break
        latest = valuation
    return latest


def _current_position(asset: Asset) -> _Position:
    return _Position(
        quantity=asset.quantity,
        cost_basis_native_minor=asset.cost_basis_native_minor,
        cost_basis_eur_minor=asset.cost_basis_eur_minor,
        cost_basis_fx_source=asset.cost_basis_fx_source,
        cost_basis_fx_rate_to_eur=asset.cost_basis_fx_rate_to_eur,
        cost_basis_fx_rate_date=asset.cost_basis_fx_rate_date,
    )


def _position_at(session: Session, asset: Asset, valued_at: date) -> _Position:
    values: dict[str, Any] = {
        "quantity": asset.quantity,
        "cost_basis_native_minor": asset.cost_basis_native_minor,
        "cost_basis_eur_minor": asset.cost_basis_eur_minor,
        "cost_basis_fx_source": asset.cost_basis_fx_source,
        "cost_basis_fx_rate_to_eur": asset.cost_basis_fx_rate_to_eur,
        "cost_basis_fx_rate_date": asset.cost_basis_fx_rate_date,
    }
    events = session.scalars(
        select(AssetEvent)
        .where(
            AssetEvent.asset_id == asset.id,
            AssetEvent.effective_at > valued_at,
        )
        .order_by(AssetEvent.previous_revision.desc())
    )
    for event in events:
        for field in POSITION_FIELDS & event.previous_values.keys():
            value = event.previous_values[field]
            if field == "cost_basis_fx_rate_date" and isinstance(value, str):
                value = date.fromisoformat(value)
            values[field] = value
    return _Position(**values)


def _month_end(value: date) -> date:
    return value.replace(day=monthrange(value.year, value.month)[1])


def _previous_month_end(value: date) -> date:
    first = value.replace(day=1)
    if first.month == 1:
        return date(first.year - 1, 12, 31)
    prior = first.replace(month=first.month - 1)
    return _month_end(prior)


def _next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _held_on(asset: Asset, day: date) -> bool:
    if asset.acquisition_date > day:
        return False
    return asset.archived_on is None or day < asset.archived_on


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _require_active(asset: Asset) -> None:
    if not asset.is_active:
        raise Problem(409, "asset_archived", "Archived assets cannot be changed")


def _check_revision(asset: Asset, expected_revision: int) -> None:
    if asset.revision != expected_revision:
        raise Problem(
            409,
            "revision_conflict",
            "Asset changed since it was loaded",
            recoverable=True,
            details={"current_revision": asset.revision},
        )


def _json_value(value: Any) -> Any:
    if hasattr(value, "value"):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    return value
