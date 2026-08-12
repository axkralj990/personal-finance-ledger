from datetime import UTC, date, datetime
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query, Request
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.api.dependencies import SessionDependency
from backend.app.api.portfolio_schemas import (
    AssetCreate,
    AssetPatch,
    AssetRead,
    ManualValuationCreate,
    QuoteConfiguration,
    ValuationRead,
)
from backend.app.config import Settings
from backend.app.database.models import Asset, AssetType, AssetValuation
from backend.app.portfolio.domain import AssetPatchData, FxPreviewData, ManualValuationData
from backend.app.portfolio.service import (
    add_manual_valuation,
    create_asset,
    get_asset,
    latest_valuation,
    list_assets,
    list_valuations,
    patch_asset,
)
from backend.app.portfolio.signing import verify_fx_preview
from backend.app.problems import Problem

router = APIRouter(prefix="/assets", tags=["portfolio"])


@router.get("", response_model=list[AssetRead])
def get_assets(
    session: SessionDependency,
    include_archived: Annotated[bool, Query()] = False,
) -> list[AssetRead]:
    assets = list_assets(session, include_archived=include_archived)
    return [_asset_read(session, asset) for asset in assets]


@router.post("", response_model=AssetRead, status_code=201)
def post_asset(request: Request, payload: AssetCreate, session: SessionDependency) -> AssetRead:
    if payload.id is not None:
        existing = session.get(Asset, str(payload.id))
        if existing is not None:
            return _idempotent_asset_read(session, existing, payload)
    signing_key = request.app.state.portfolio_signing_key
    _verify_fx_token(
        signing_key,
        payload.currency,
        payload.acquisition_date,
        payload.cost_basis_fx_source,
        payload.cost_basis_fx_rate_to_eur,
        payload.cost_basis_fx_rate_date,
        payload.cost_basis_fx_preview_token,
    )
    _verify_valuation_fx_token(signing_key, payload.currency, payload.initial_valuation.to_domain())
    try:
        asset = create_asset(session, payload.to_domain())
    except IntegrityError:
        session.rollback()
        existing = session.get(Asset, str(payload.id)) if payload.id is not None else None
        if existing is None:
            raise
        return _idempotent_asset_read(session, existing, payload)
    return _asset_read(session, asset)


@router.get("/{asset_id}", response_model=AssetRead)
def get_asset_by_id(asset_id: str, session: SessionDependency) -> AssetRead:
    return _asset_read(session, get_asset(session, asset_id))


@router.patch("/{asset_id}", response_model=AssetRead)
def patch_asset_by_id(
    request: Request,
    asset_id: str,
    payload: AssetPatch,
    session: SessionDependency,
) -> AssetRead:
    excluded = {
        "expected_revision",
        "effective_at",
        "replacement_valuation",
        "quote",
        "cost_basis_fx_preview_token",
    }
    changes: dict[str, Any] = payload.model_dump(exclude_unset=True, exclude=excluded)
    if "quote" in payload.model_fields_set:
        quote = payload.quote
        changes.update(
            {
                "quote_symbol": quote.symbol if quote else None,
                "quote_exchange": quote.exchange if quote else None,
                "quote_mic_code": quote.mic_code if quote else None,
            }
        )
    current = get_asset(session, asset_id)
    if "asset_type" in changes and changes["asset_type"] != current.asset_type:
        raise Problem(
            422,
            "immutable_asset_type",
            "Asset type cannot be changed after creation",
            field="asset_type",
            recoverable=True,
        )
    security_purchase_fields = {
        "quantity",
        "cost_basis_native_minor",
        "cost_basis_eur_minor",
        "cost_basis_fx_source",
        "cost_basis_fx_rate_to_eur",
        "cost_basis_fx_rate_date",
    }
    if (
        current.asset_type in {AssetType.ETF, AssetType.STOCK}
        and security_purchase_fields & payload.model_fields_set
    ):
        raise Problem(
            422,
            "immutable_security_purchase",
            "Security purchase facts cannot be changed after creation",
            field="quantity",
            recoverable=True,
        )
    cost_fields = {
        "cost_basis_native_minor",
        "cost_basis_eur_minor",
        "cost_basis_fx_source",
        "cost_basis_fx_rate_to_eur",
        "cost_basis_fx_rate_date",
    }
    if cost_fields & payload.model_fields_set:
        _verify_fx_token(
            request.app.state.portfolio_signing_key,
            current.currency,
            payload.effective_at or current.acquisition_date,
            changes.get("cost_basis_fx_source", current.cost_basis_fx_source),
            changes.get("cost_basis_fx_rate_to_eur", current.cost_basis_fx_rate_to_eur),
            changes.get("cost_basis_fx_rate_date", current.cost_basis_fx_rate_date),
            payload.cost_basis_fx_preview_token,
        )
    elif payload.cost_basis_fx_preview_token is not None:
        raise Problem(
            422,
            "unexpected_fx_preview_token",
            "FX preview token requires ECB cost basis changes",
            field="cost_basis_fx_preview_token",
        )
    replacement = (
        payload.replacement_valuation.to_domain() if payload.replacement_valuation else None
    )
    if replacement is not None:
        _verify_valuation_fx_token(
            request.app.state.portfolio_signing_key, current.currency, replacement
        )
    asset = patch_asset(
        session,
        asset_id,
        AssetPatchData(
            expected_revision=payload.expected_revision,
            changes=changes,
            effective_at=payload.effective_at,
            replacement_valuation=replacement,
            cost_basis_fx_preview_token=payload.cost_basis_fx_preview_token,
            archived_on=(
                _archive_date(request.app.state.settings)
                if changes.get("is_active") is False
                else None
            ),
        ),
    )
    return _asset_read(session, asset)


@router.get("/{asset_id}/valuations", response_model=list[ValuationRead])
def get_asset_valuations(asset_id: str, session: SessionDependency) -> list[ValuationRead]:
    return [ValuationRead.model_validate(item) for item in list_valuations(session, asset_id)]


@router.post("/{asset_id}/valuations", response_model=ValuationRead, status_code=201)
def post_asset_valuation(
    request: Request,
    asset_id: str,
    payload: ManualValuationCreate,
    session: SessionDependency,
) -> ValuationRead:
    asset = get_asset(session, asset_id)
    valuation_data = payload.to_domain()
    _verify_valuation_fx_token(
        request.app.state.portfolio_signing_key, asset.currency, valuation_data
    )
    valuation = add_manual_valuation(
        session,
        asset_id,
        valuation_data,
        payload.expected_revision,
    )
    return ValuationRead.model_validate(valuation)


def _asset_read(session: Session, asset: Asset) -> AssetRead:
    quote = None
    if asset.quote_symbol is not None:
        quote = QuoteConfiguration(
            symbol=asset.quote_symbol,
            exchange=asset.quote_exchange,
            mic_code=asset.quote_mic_code,
        )
    valuation = latest_valuation(session, asset.id)
    return AssetRead(
        id=asset.id,
        name=asset.name,
        asset_type=asset.asset_type,
        currency=asset.currency,
        acquisition_date=asset.acquisition_date,
        quantity=asset.quantity,
        cost_basis_native_minor=asset.cost_basis_native_minor,
        cost_basis_eur_minor=asset.cost_basis_eur_minor,
        cost_basis_fx_source=asset.cost_basis_fx_source,
        cost_basis_fx_rate_to_eur=asset.cost_basis_fx_rate_to_eur,
        cost_basis_fx_rate_date=asset.cost_basis_fx_rate_date,
        quote=quote,
        is_active=asset.is_active,
        revision=asset.revision,
        created_at=asset.created_at,
        updated_at=asset.updated_at,
        archived_at=asset.archived_at,
        archived_on=asset.archived_on,
        latest_valuation=(ValuationRead.model_validate(valuation) if valuation else None),
    )


def _idempotent_asset_read(
    session: Session, asset: Asset, payload: AssetCreate
) -> AssetRead:
    initial = session.scalar(
        select(AssetValuation)
        .where(AssetValuation.asset_id == asset.id)
        .order_by(AssetValuation.created_at, AssetValuation.id)
        .limit(1)
    )
    quote = payload.quote
    valuation = payload.initial_valuation
    matches = initial is not None and (
        asset.name == payload.name
        and asset.asset_type == payload.asset_type
        and asset.currency == payload.currency
        and asset.acquisition_date == payload.acquisition_date
        and asset.quantity == payload.quantity
        and asset.cost_basis_native_minor == payload.cost_basis_native_minor
        and asset.cost_basis_eur_minor == payload.cost_basis_eur_minor
        and asset.cost_basis_fx_source == payload.cost_basis_fx_source
        and asset.cost_basis_fx_rate_to_eur == payload.cost_basis_fx_rate_to_eur
        and asset.cost_basis_fx_rate_date == payload.cost_basis_fx_rate_date
        and asset.quote_symbol == (quote.symbol if quote else None)
        and asset.quote_exchange == (quote.exchange if quote else None)
        and asset.quote_mic_code == (quote.mic_code if quote else None)
        and initial.valued_at == valuation.valued_at
        and initial.native_value_minor == valuation.native_value_minor
        and initial.unit_price == valuation.unit_price
        and initial.fx_source == valuation.fx_source
        and initial.fx_rate_to_eur == valuation.fx_rate_to_eur
        and initial.fx_rate_date == valuation.fx_rate_date
    )
    if not matches:
        raise Problem(
            409,
            "asset_id_reused",
            "Asset create ID was already used for a different purchase",
            field="id",
            recoverable=True,
        )
    return _asset_read(session, asset)


def _verify_valuation_fx_token(
    signing_key: bytes, currency: str, valuation: ManualValuationData
) -> None:
    _verify_fx_token(
        signing_key,
        currency,
        valuation.valued_at,
        valuation.fx_source,
        valuation.fx_rate_to_eur,
        valuation.fx_rate_date,
        valuation.fx_preview_token,
    )


def _verify_fx_token(
    signing_key: bytes,
    currency: str,
    valued_at: date,
    source: str | None,
    rate_to_eur: str | None,
    rate_date: date | None,
    preview_token: str | None,
) -> None:
    if source not in {"ECB", "IDENTITY"}:
        if preview_token is not None:
            raise Problem(
                422,
                "unexpected_fx_preview_token",
                "FX preview token is not valid for manual provenance",
                recoverable=True,
            )
        return
    if source == "IDENTITY" and preview_token is None:
        return
    if rate_to_eur is None or rate_date is None or preview_token is None:
        raise Problem(
            409,
            "invalid_fx_preview_token",
            "Provider FX provenance requires a valid preview token",
            recoverable=True,
        )
    preview = FxPreviewData(
        currency=currency,
        valued_at=valued_at,
        source=source,
        rate_to_eur=rate_to_eur,
        rate_date=rate_date,
    )
    if not verify_fx_preview(signing_key, preview, preview_token):
        raise Problem(
            409,
            "invalid_fx_preview_token",
            "FX preview token does not match the submitted provenance",
            recoverable=True,
        )


def _archive_date(settings: Settings, now: datetime | None = None) -> date:
    current = now or datetime.now(UTC)
    return current.astimezone(ZoneInfo(settings.timezone)).date()
