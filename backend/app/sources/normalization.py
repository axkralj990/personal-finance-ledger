import hashlib
import json
import re
import unicodedata
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

import pandas as pd


def normalize_header(value: str) -> str:
    ascii_value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "", ascii_value.casefold())


def normalize_description(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def amount_to_minor(value: Any) -> int:
    if value is None or bool(pd.isna(value)):
        raise ValueError("amount is missing")
    raw = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        raw = raw.replace(",", ".")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"invalid amount: {value}") from exc
    return int((amount * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def json_value(value: Any) -> Any:
    if value is None or bool(pd.isna(value)):
        return None
    if isinstance(value, datetime | date):
        return value.isoformat()
    if hasattr(value, "item"):
        return value.item()
    return value


def row_fingerprint(provider: str, raw: dict[str, Any], canonical: dict[str, Any]) -> str:
    ignored = {"balance", "runningbalance", "saldo", "stanje"}
    stable_raw = {
        normalize_header(str(key)): json_value(value)
        for key, value in raw.items()
        if normalize_header(str(key)) not in ignored
    }
    payload = {"provider": provider, "raw": stable_raw, "canonical": canonical}
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()
