import hashlib
import hmac
import json
from datetime import UTC

from backend.app.portfolio.domain import FxPreviewData, QuoteSnapshotData


def sign_quote_preview(signing_key: bytes, snapshot: QuoteSnapshotData) -> str:
    return hmac.new(signing_key, _payload(snapshot), hashlib.sha256).hexdigest()


def verify_quote_preview(
    signing_key: bytes, snapshot: QuoteSnapshotData, preview_token: str
) -> bool:
    expected = sign_quote_preview(signing_key, snapshot)
    return hmac.compare_digest(expected, preview_token)


def sign_fx_preview(signing_key: bytes, preview: FxPreviewData) -> str:
    data = {
        "currency": preview.currency,
        "rate_date": preview.rate_date.isoformat(),
        "rate_to_eur": preview.rate_to_eur,
        "source": preview.source,
        "valued_at": preview.valued_at.isoformat(),
    }
    payload = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    return hmac.new(signing_key, payload, hashlib.sha256).hexdigest()


def verify_fx_preview(signing_key: bytes, preview: FxPreviewData, preview_token: str) -> bool:
    return hmac.compare_digest(sign_fx_preview(signing_key, preview), preview_token)


def _payload(snapshot: QuoteSnapshotData) -> bytes:
    fetched_at = snapshot.quote_fetched_at.astimezone(UTC).isoformat(timespec="microseconds")
    data = {
        "asset_id": snapshot.asset_id,
        "asset_revision": snapshot.asset_revision,
        "eur_value_minor": snapshot.eur_value_minor,
        "fx_rate_date": snapshot.fx_rate_date.isoformat(),
        "fx_rate_to_eur": snapshot.fx_rate_to_eur,
        "fx_source": snapshot.fx_source,
        "native_currency": snapshot.native_currency,
        "native_value_minor": snapshot.native_value_minor,
        "quantity": snapshot.quantity,
        "quote_exchange": snapshot.quote_exchange,
        "quote_fetched_at": fetched_at,
        "quote_interval": snapshot.quote_interval.value,
        "quote_mic_code": snapshot.quote_mic_code,
        "quote_name": snapshot.quote_name,
        "quote_symbol": snapshot.quote_symbol,
        "source": snapshot.source.value,
        "status": "ready",
        "unit_price": snapshot.unit_price,
        "valued_at": snapshot.valued_at.isoformat(),
    }
    return json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
