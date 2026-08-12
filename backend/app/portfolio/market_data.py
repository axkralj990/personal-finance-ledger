from __future__ import annotations

import csv
import io
from calendar import monthrange
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any
from urllib.parse import quote as url_quote
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import httpx

from backend.app.config import Settings
from backend.app.database.models import Asset, AssetType, QuoteInterval, ValuationSource
from backend.app.portfolio.domain import FxPreviewData, QuoteSnapshotData
from backend.app.portfolio.precision import (
    SUPPORTED_PORTFOLIO_CURRENCIES,
    canonical_decimal,
    convert_minor_to_eur,
    parse_decimal,
    position_value_minor,
)


class MarketDataError(Exception):
    def __init__(self, code: str, message: str, recoverable: bool = True) -> None:
        self.code = code
        self.message = message
        self.recoverable = recoverable
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class _Quote:
    symbol: str
    name: str
    exchange: str | None
    mic_code: str | None
    currency: str
    valued_at: date
    unit_price: str
    fetched_at: datetime


@dataclass(frozen=True, slots=True)
class _YahooVenue:
    key: str
    suffix: str
    exchange_names: frozenset[str]


_LONDON = _YahooVenue("LONDON", ".L", frozenset({"LSE"}))
_AMSTERDAM = _YahooVenue("AMSTERDAM", ".AS", frozenset({"AMS"}))
_XETRA = _YahooVenue("XETRA", ".DE", frozenset({"GER"}))
_YAHOO_VENUES = {
    "LSEETF": _LONDON,
    "LSE": _LONDON,
    "XLON": _LONDON,
    "AEB": _AMSTERDAM,
    "AMS": _AMSTERDAM,
    "XAMS": _AMSTERDAM,
    "IBIS2": _XETRA,
    "XETRA": _XETRA,
    "GER": _XETRA,
    "XETR": _XETRA,
}


class MarketDataClient:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        timeout = httpx.Timeout(settings.market_data_timeout_seconds)
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "personal-finance-portfolio/1.0"},
        )
        self._fx_cache: dict[tuple[str, date], tuple[str, date]] = {}
        self._quote_cache: dict[tuple[str, str, str], _Quote | MarketDataError] = {}

    def __enter__(self) -> MarketDataClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self._client.close()

    def preview(self, asset: Asset) -> QuoteSnapshotData:
        self._validate_asset(asset)
        quote, source = self._fetch_market_quote(asset)
        if quote.currency != asset.currency:
            raise MarketDataError(
                "quote_currency_mismatch",
                "Provider quote currency does not match the asset currency",
                False,
            )
        quantity = parse_decimal(asset.quantity or "", "quantity", positive=True)
        unit_price = parse_decimal(quote.unit_price, "unit_price", positive=True)
        native_value = position_value_minor(quantity, unit_price)
        fx = self.fx_preview(asset.currency, quote.valued_at)
        return QuoteSnapshotData(
            asset_id=asset.id,
            asset_revision=asset.revision,
            source=source,
            quote_interval=QuoteInterval.LIVE,
            valued_at=quote.valued_at,
            native_currency=asset.currency,
            native_value_minor=native_value,
            eur_value_minor=convert_minor_to_eur(native_value, Decimal(fx.rate_to_eur)),
            quantity=asset.quantity or "",
            unit_price=quote.unit_price,
            quote_symbol=asset.quote_symbol or "",
            quote_exchange=asset.quote_exchange,
            quote_mic_code=asset.quote_mic_code,
            quote_name=quote.name,
            quote_fetched_at=quote.fetched_at,
            fx_source=fx.source,
            fx_rate_to_eur=fx.rate_to_eur,
            fx_rate_date=fx.rate_date,
        )

    def history(self, asset: Asset) -> tuple[QuoteSnapshotData, ...]:
        self._validate_asset(asset)
        quotes = self._fetch_yahoo_history(asset)
        if not quotes:
            return ()
        fx_by_date = self.fx_previews(asset.currency, [quote.valued_at for quote in quotes])
        quantity = parse_decimal(asset.quantity or "", "quantity", positive=True)
        snapshots: list[QuoteSnapshotData] = []
        for quote in quotes:
            unit_price = parse_decimal(quote.unit_price, "unit_price", positive=True)
            native_value = position_value_minor(quantity, unit_price)
            fx = fx_by_date[quote.valued_at]
            snapshots.append(
                QuoteSnapshotData(
                    asset_id=asset.id,
                    asset_revision=asset.revision,
                    source=ValuationSource.YAHOO_FINANCE,
                    quote_interval=QuoteInterval.MONTHLY,
                    valued_at=quote.valued_at,
                    native_currency=asset.currency,
                    native_value_minor=native_value,
                    eur_value_minor=convert_minor_to_eur(
                        native_value, Decimal(fx.rate_to_eur)
                    ),
                    quantity=asset.quantity or "",
                    unit_price=quote.unit_price,
                    quote_symbol=asset.quote_symbol or "",
                    quote_exchange=asset.quote_exchange,
                    quote_mic_code=asset.quote_mic_code,
                    quote_name=quote.name,
                    quote_fetched_at=quote.fetched_at,
                    fx_source=fx.source,
                    fx_rate_to_eur=fx.rate_to_eur,
                    fx_rate_date=fx.rate_date,
                )
            )
        return tuple(snapshots)

    def fx_preview(self, currency: str, valued_at: date) -> FxPreviewData:
        if currency not in SUPPORTED_PORTFOLIO_CURRENCIES:
            raise MarketDataError(
                "unsupported_portfolio_currency",
                "Currency is not supported by portfolio v1",
                False,
            )
        if currency == "EUR":
            return FxPreviewData(
                currency=currency,
                valued_at=valued_at,
                source="IDENTITY",
                rate_to_eur="1",
                rate_date=valued_at,
            )
        cache_key = (currency, valued_at)
        cached = self._fx_cache.get(cache_key)
        if cached is None:
            cached = self._fetch_ecb_rate(currency, valued_at)
            self._fx_cache[cache_key] = cached
        return FxPreviewData(
            currency=currency,
            valued_at=valued_at,
            source="ECB",
            rate_to_eur=cached[0],
            rate_date=cached[1],
        )

    def fx_previews(self, currency: str, valued_at: list[date]) -> dict[date, FxPreviewData]:
        dates = sorted(set(valued_at))
        if not dates:
            return {}
        if currency == "EUR":
            return {
                current: FxPreviewData(currency, current, "IDENTITY", "1", current)
                for current in dates
            }
        if currency not in SUPPORTED_PORTFOLIO_CURRENCIES:
            raise MarketDataError(
                "unsupported_portfolio_currency",
                "Currency is not supported by portfolio v1",
                False,
            )
        rates = self._fetch_ecb_rates(currency, dates)
        return {
            current: FxPreviewData(currency, current, "ECB", rate, rate_date)
            for current, (rate, rate_date) in rates.items()
        }

    def _validate_asset(self, asset: Asset) -> None:
        if not asset.is_active:
            raise MarketDataError("asset_archived", "Archived assets cannot be quoted", False)
        if (
            asset.asset_type not in {AssetType.ETF, AssetType.STOCK}
            or asset.quote_symbol is None
            or asset.quantity is None
            or not (asset.quote_exchange or asset.quote_mic_code)
        ):
            raise MarketDataError(
                "quote_not_configured",
                "Asset does not have a complete market quote configuration",
                False,
            )
    def _fetch_market_quote(self, asset: Asset) -> tuple[_Quote, ValuationSource]:
        venue = _yahoo_venue(asset)
        cache_key = (asset.quote_symbol or "", venue.key, asset.currency)
        cached = self._quote_cache.get(cache_key)
        if isinstance(cached, MarketDataError):
            raise cached
        if cached is not None:
            return cached, ValuationSource.YAHOO_FINANCE
        try:
            quote = self._fetch_yahoo_quote(asset, venue)
        except MarketDataError as exc:
            self._quote_cache[cache_key] = exc
            raise
        self._quote_cache[cache_key] = quote
        return quote, ValuationSource.YAHOO_FINANCE

    def _fetch_yahoo_quote(self, asset: Asset, venue: _YahooVenue | None = None) -> _Quote:
        venue = venue or _yahoo_venue(asset)
        yahoo_symbol = _yahoo_symbol(asset, venue)
        response = self._request(
            f"{self._settings.yahoo_finance_base_url.rstrip('/')}/v8/finance/chart/"
            f"{url_quote(yahoo_symbol, safe='.-')}",
            params={"interval": "1d", "range": "5d"},
        )
        try:
            payload = response.json()
            chart = payload["chart"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataError(
                "yahoo_provider_invalid_response",
                "Yahoo Finance returned incomplete quote data",
            ) from exc
        if chart.get("error") is not None:
            raise MarketDataError(
                "yahoo_provider_error",
                _provider_error_message(
                    chart["error"], "Yahoo Finance could not return this quote"
                ),
            )
        try:
            result = chart["result"][0]
            meta = result["meta"]
            provider_symbol = str(meta["symbol"]).strip().upper()
            currency = str(meta["currency"]).strip().upper()
            exchange = str(meta["exchangeName"]).strip().upper()
            unit_price = _provider_decimal(meta["regularMarketPrice"], positive=True)
            market_time = int(meta["regularMarketTime"])
            timezone_name = str(meta["exchangeTimezoneName"])
            name = _provider_name(meta.get("longName") or meta.get("shortName"))
            market_date = datetime.fromtimestamp(
                market_time, ZoneInfo(timezone_name)
            ).date()
        except (
            IndexError,
            KeyError,
            TypeError,
            ValueError,
            ZoneInfoNotFoundError,
        ) as exc:
            raise MarketDataError(
                "yahoo_provider_invalid_response",
                "Yahoo Finance returned incomplete quote data",
            ) from exc
        if provider_symbol != yahoo_symbol or exchange not in venue.exchange_names:
            raise MarketDataError(
                "yahoo_identity_mismatch",
                "Yahoo Finance instrument identity does not match the configured ticker and venue",
                False,
            )
        if currency != asset.currency:
            raise MarketDataError(
                "quote_currency_mismatch",
                "Yahoo Finance quote currency does not match the asset currency",
                False,
            )
        return _Quote(
            symbol=asset.quote_symbol or "",
            name=name,
            exchange=asset.quote_exchange,
            mic_code=asset.quote_mic_code,
            currency=currency,
            valued_at=market_date,
            unit_price=unit_price,
            fetched_at=datetime.now(UTC),
        )

    def _fetch_yahoo_history(self, asset: Asset) -> tuple[_Quote, ...]:
        venue = _yahoo_venue(asset)
        yahoo_symbol = _yahoo_symbol(asset, venue)
        current_month = datetime.now(ZoneInfo(self._settings.timezone)).date().replace(day=1)
        first_month = asset.acquisition_date.replace(day=1)
        if first_month >= current_month:
            return ()
        period1 = int(datetime.combine(first_month, datetime.min.time(), UTC).timestamp())
        period2 = int(datetime.combine(current_month, datetime.min.time(), UTC).timestamp())
        response = self._request(
            f"{self._settings.yahoo_finance_base_url.rstrip('/')}/v8/finance/chart/"
            f"{url_quote(yahoo_symbol, safe='.-')}",
            params={
                "interval": "1mo",
                "period1": str(period1),
                "period2": str(period2),
                "events": "history,splits",
            },
        )
        try:
            payload = response.json()
            chart = payload["chart"]
        except (KeyError, TypeError, ValueError) as exc:
            raise MarketDataError(
                "yahoo_history_invalid_response",
                "Yahoo Finance returned incomplete monthly history",
            ) from exc
        if chart.get("error") is not None:
            raise MarketDataError(
                "yahoo_history_provider_error",
                _provider_error_message(
                    chart["error"], "Yahoo Finance could not return monthly history"
                ),
            )
        try:
            result = chart["result"][0]
            meta = result["meta"]
            provider_symbol = str(meta["symbol"]).strip().upper()
            currency = str(meta["currency"]).strip().upper()
            exchange = str(meta["exchangeName"]).strip().upper()
            timezone_name = str(meta["exchangeTimezoneName"])
            name = _provider_name(meta.get("longName") or meta.get("shortName"))
            price_hint = int(meta.get("priceHint", 2))
            timestamps = result["timestamp"]
            closes = result["indicators"]["quote"][0]["close"]
            split_events = result.get("events", {}).get("splits", {})
        except (IndexError, KeyError, TypeError, ValueError) as exc:
            raise MarketDataError(
                "yahoo_history_invalid_response",
                "Yahoo Finance returned incomplete monthly history",
            ) from exc
        if (
            provider_symbol != yahoo_symbol
            or exchange not in venue.exchange_names
            or currency != asset.currency
        ):
            raise MarketDataError(
                "yahoo_identity_mismatch",
                "Yahoo Finance history does not match the configured instrument",
                False,
            )
        if any(
            datetime.fromtimestamp(int(event["date"]), UTC).date() >= asset.acquisition_date
            for event in split_events.values()
        ):
            raise MarketDataError(
                "security_split_requires_review",
                "A security split occurred after acquisition; historical quantity requires review",
                False,
            )
        fetched_at = datetime.now(UTC)
        quotes: list[_Quote] = []
        try:
            timezone = ZoneInfo(timezone_name)
            for timestamp, close in zip(timestamps, closes, strict=True):
                if close is None:
                    continue
                month = datetime.fromtimestamp(int(timestamp), timezone).date().replace(day=1)
                month_end = month.replace(day=monthrange(month.year, month.month)[1])
                if month_end < asset.acquisition_date or month >= current_month:
                    continue
                quotes.append(
                    _Quote(
                        symbol=asset.quote_symbol or "",
                        name=name,
                        exchange=asset.quote_exchange,
                        mic_code=asset.quote_mic_code,
                        currency=currency,
                        valued_at=month_end,
                        unit_price=_provider_price(close, price_hint),
                        fetched_at=fetched_at,
                    )
                )
        except (TypeError, ValueError, ZoneInfoNotFoundError) as exc:
            raise MarketDataError(
                "yahoo_history_invalid_response",
                "Yahoo Finance returned invalid monthly history values",
            ) from exc
        return tuple(sorted(quotes, key=lambda item: item.valued_at))

    def _fetch_ecb_rate(self, currency: str, valued_at: date) -> tuple[str, date]:
        url = f"{self._settings.ecb_data_base_url.rstrip('/')}/EXR/D.{currency}.EUR.SP00.A"
        response = self._request(
            url,
            params={
                "endPeriod": valued_at.isoformat(),
                "lastNObservations": "1",
                "format": "csvdata",
            },
        )
        rows = csv.DictReader(io.StringIO(response.text))
        candidates: list[tuple[date, Decimal]] = []
        try:
            for row in rows:
                rate_date = date.fromisoformat(row["TIME_PERIOD"])
                if rate_date <= valued_at:
                    candidates.append((rate_date, Decimal(row["OBS_VALUE"])))
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise MarketDataError(
                "fx_provider_invalid_response",
                "ECB returned invalid exchange-rate data",
            ) from exc
        if not candidates:
            raise MarketDataError(
                "fx_rate_unavailable",
                f"No ECB reference rate is available for {currency}",
            )
        rate_date, foreign_per_eur = max(candidates, key=lambda item: item[0])
        if not foreign_per_eur.is_finite() or foreign_per_eur <= 0:
            raise MarketDataError(
                "fx_provider_invalid_response",
                "ECB returned an invalid exchange rate",
            )
        rate_to_eur = (Decimal(1) / foreign_per_eur).quantize(
            Decimal("0.000000000000000001"), rounding=ROUND_HALF_UP
        )
        return canonical_decimal(rate_to_eur), rate_date

    def _fetch_ecb_rates(
        self, currency: str, valued_at: list[date]
    ) -> dict[date, tuple[str, date]]:
        start = min(valued_at) - timedelta(days=10)
        end = max(valued_at)
        url = f"{self._settings.ecb_data_base_url.rstrip('/')}/EXR/D.{currency}.EUR.SP00.A"
        response = self._request(
            url,
            params={
                "startPeriod": start.isoformat(),
                "endPeriod": end.isoformat(),
                "format": "csvdata",
            },
        )
        observations: list[tuple[date, Decimal]] = []
        try:
            for row in csv.DictReader(io.StringIO(response.text)):
                rate_date = date.fromisoformat(row["TIME_PERIOD"])
                foreign_per_eur = Decimal(row["OBS_VALUE"])
                if foreign_per_eur.is_finite() and foreign_per_eur > 0:
                    observations.append((rate_date, foreign_per_eur))
        except (KeyError, InvalidOperation, TypeError, ValueError) as exc:
            raise MarketDataError(
                "fx_provider_invalid_response",
                "ECB returned invalid exchange-rate history",
            ) from exc
        results: dict[date, tuple[str, date]] = {}
        for target in valued_at:
            candidates = [item for item in observations if item[0] <= target]
            if not candidates:
                raise MarketDataError(
                    "fx_rate_unavailable",
                    f"No ECB reference rate is available for {currency} on {target.isoformat()}",
                )
            rate_date, foreign_per_eur = max(candidates, key=lambda item: item[0])
            rate = (Decimal(1) / foreign_per_eur).quantize(
                Decimal("0.000000000000000001"), rounding=ROUND_HALF_UP
            )
            rendered = canonical_decimal(rate)
            results[target] = (rendered, rate_date)
            self._fx_cache[(currency, target)] = (rendered, rate_date)
        return results

    def _request(
        self,
        url: str,
        *,
        params: dict[str, str],
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = self._client.get(url, params=params, headers=headers)
            response.raise_for_status()
            return response
        except httpx.TimeoutException as exc:
            raise MarketDataError(
                "market_data_timeout",
                "The market data provider timed out",
            ) from exc
        except httpx.HTTPStatusError as exc:
            raise MarketDataError(
                "market_data_http_error",
                _provider_error_message(
                    _response_json(exc.response),
                    "The market data provider returned an error",
                ),
                exc.response.status_code == 429 or exc.response.status_code >= 500,
            ) from exc
        except httpx.RequestError as exc:
            raise MarketDataError(
                "market_data_unavailable",
                "The market data provider is unavailable",
            ) from exc


def _provider_decimal(value: Any, *, positive: bool) -> str:
    try:
        parsed = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("invalid provider decimal") from exc
    if not parsed.is_finite() or parsed < 0 or (positive and parsed <= 0):
        raise ValueError("invalid provider decimal")
    return canonical_decimal(parsed)


def _provider_price(value: Any, price_hint: int) -> str:
    parsed = Decimal(_provider_decimal(value, positive=True))
    places = min(max(price_hint, 0), 8)
    rounded = parsed.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    return canonical_decimal(rounded)


def _yahoo_venue(asset: Asset) -> _YahooVenue:
    configured = {
        value.strip().upper()
        for value in (asset.quote_exchange, asset.quote_mic_code)
        if value and value.strip()
    }
    venues = {_YAHOO_VENUES[value] for value in configured if value in _YAHOO_VENUES}
    unsupported = configured - _YAHOO_VENUES.keys()
    if unsupported or len(venues) != 1:
        rendered = "/".join(sorted(configured)) or "unknown"
        raise MarketDataError(
            "yahoo_exchange_unsupported",
            f"Yahoo Finance is not configured for exchange {rendered}",
            False,
        )
    return venues.pop()


def _yahoo_symbol(asset: Asset, venue: _YahooVenue | None = None) -> str:
    current_venue = venue or _yahoo_venue(asset)
    return f"{asset.quote_symbol}{current_venue.suffix}"


def _response_json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError:
        return None


def _provider_error_message(payload: Any, fallback: str) -> str:
    if isinstance(payload, dict) and isinstance(payload.get("message"), str):
        message = payload["message"].strip()
        if message:
            return message[:500]
    return fallback


def _provider_name(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("quote name is missing")
    return value.strip()


def _optional_upper(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip().upper()
    return normalized or None
