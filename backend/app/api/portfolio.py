from datetime import date
from typing import Annotated

from fastapi import APIRouter, Query, Request
from sqlalchemy import select

from backend.app.api.dependencies import SessionDependency
from backend.app.api.portfolio_schemas import (
    FxPreviewRead,
    PortfolioRead,
    QuoteError,
    QuoteHistoryPreviewRead,
    QuotePreviewError,
    QuotePreviewItem,
    QuotePreviewReady,
    QuotePreviewResponse,
    QuoteSnapshotsCreate,
    QuoteSnapshotsRead,
    ValuationRead,
)
from backend.app.database.models import AssetValuation, QuoteInterval, ValuationSource
from backend.app.portfolio.market_data import MarketDataError
from backend.app.portfolio.service import (
    build_portfolio,
    get_asset,
    persist_quote_snapshots,
)
from backend.app.portfolio.signing import (
    sign_fx_preview,
    sign_quote_preview,
    verify_quote_preview,
)
from backend.app.problems import Problem

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.get("", response_model=PortfolioRead)
def get_portfolio(
    session: SessionDependency,
    as_of: Annotated[date | None, Query()] = None,
) -> PortfolioRead:
    return PortfolioRead.model_validate(build_portfolio(session, as_of or date.today()))


@router.get("/quote-preview", response_model=QuotePreviewResponse)
def get_quote_preview(
    request: Request,
    session: SessionDependency,
    asset_id: Annotated[list[str], Query(min_length=1)],
) -> QuotePreviewResponse:
    if len(set(asset_id)) != len(asset_id):
        raise Problem(422, "duplicate_asset_id", "asset_id values must be unique")
    items: list[QuotePreviewItem] = []
    factory = request.app.state.market_data_client_factory
    with factory(request.app.state.settings) as provider:
        for current_id in asset_id:
            asset = None
            try:
                asset = get_asset(session, current_id)
                snapshot = provider.preview(asset)
                token = sign_quote_preview(request.app.state.portfolio_signing_key, snapshot)
                items.append(QuotePreviewReady.from_domain(snapshot, token))
            except MarketDataError as exc:
                items.append(
                    QuotePreviewError(
                        asset_id=current_id,
                        asset_revision=asset.revision if asset else None,
                        error=QuoteError(
                            code=exc.code,
                            message=exc.message,
                            recoverable=exc.recoverable,
                        ),
                    )
                )
            except Problem as exc:
                items.append(
                    QuotePreviewError(
                        asset_id=current_id,
                        asset_revision=asset.revision if asset else None,
                        error=QuoteError(
                            code=exc.body.code,
                            message=exc.body.message,
                            recoverable=exc.body.recoverable,
                        ),
                    )
                )
    return QuotePreviewResponse(items=items)


@router.get("/history-preview", response_model=QuoteHistoryPreviewRead)
def get_history_preview(
    request: Request,
    session: SessionDependency,
    asset_id: Annotated[str, Query(min_length=1)],
) -> QuoteHistoryPreviewRead:
    asset = get_asset(session, asset_id)
    factory = request.app.state.market_data_client_factory
    try:
        with factory(request.app.state.settings) as provider:
            snapshots = provider.history(asset)
    except MarketDataError as exc:
        raise Problem(
            503 if exc.recoverable else 422,
            exc.code,
            exc.message,
            recoverable=exc.recoverable,
        ) from exc
    existing_dates = set(
        session.scalars(
            select(AssetValuation.valued_at).where(
                AssetValuation.asset_id == asset.id,
                AssetValuation.source == ValuationSource.YAHOO_FINANCE,
                AssetValuation.quote_interval == QuoteInterval.MONTHLY,
            )
        )
    )
    missing = [snapshot for snapshot in snapshots if snapshot.valued_at not in existing_dates]
    items = [
        QuotePreviewReady.from_domain(
            snapshot,
            sign_quote_preview(request.app.state.portfolio_signing_key, snapshot),
        )
        for snapshot in missing
    ]
    dates = [snapshot.valued_at for snapshot in snapshots]
    return QuoteHistoryPreviewRead(
        asset_id=asset.id,
        asset_revision=asset.revision,
        available_months=len(snapshots),
        existing_months=len(snapshots) - len(missing),
        first_date=min(dates) if dates else None,
        last_date=max(dates) if dates else None,
        items=items,
    )


@router.get("/fx-preview", response_model=FxPreviewRead)
def get_fx_preview(
    request: Request,
    currency: Annotated[str, Query(min_length=3, max_length=3)],
    valued_at: Annotated[date, Query()],
) -> FxPreviewRead:
    factory = request.app.state.market_data_client_factory
    try:
        with factory(request.app.state.settings) as provider:
            preview = provider.fx_preview(currency.upper(), valued_at)
    except MarketDataError as exc:
        raise Problem(
            503 if exc.recoverable else 422,
            exc.code,
            exc.message,
            recoverable=exc.recoverable,
        ) from exc
    return FxPreviewRead(
        currency=preview.currency,
        valued_at=preview.valued_at,
        source=preview.source,
        rate_to_eur=preview.rate_to_eur,
        rate_date=preview.rate_date,
        preview_token=sign_fx_preview(request.app.state.portfolio_signing_key, preview),
    )


@router.post("/quote-snapshots", response_model=QuoteSnapshotsRead, status_code=201)
def post_quote_snapshots(
    request: Request, payload: QuoteSnapshotsCreate, session: SessionDependency
) -> QuoteSnapshotsRead:
    snapshots = tuple(item.to_domain() for item in payload.items)
    if any(
        not verify_quote_preview(
            request.app.state.portfolio_signing_key, snapshot, item.preview_token
        )
        for item, snapshot in zip(payload.items, snapshots, strict=True)
    ):
        raise Problem(
            409,
            "invalid_preview_token",
            "Quote preview token is invalid or stale",
            recoverable=True,
        )
    valuations = persist_quote_snapshots(
        session,
        snapshots,
        max_age_hours=request.app.state.settings.quote_preview_max_age_hours,
    )
    return QuoteSnapshotsRead(
        items=[ValuationRead.model_validate(valuation) for valuation in valuations]
    )
