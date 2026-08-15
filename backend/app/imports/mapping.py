from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Callable, Mapping, Sequence
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from backend.app.database.models import StagedDisposition, TransactionKind
from backend.app.imports.inspection import normalize_label, read_source_rows
from backend.app.imports.models import (
    ISO_CURRENCY_CODES,
    ConstantCurrency,
    DateSource,
    DebitCreditAmount,
    ExpenseSignConvention,
    ImportInspection,
    NumberFormat,
    OptionalTextSource,
    SignedAmount,
    SourceCurrency,
    SourceRow,
    TextSource,
    TimestampSource,
    UniversalMappingSpec,
)
from backend.app.sources.base import ParsedRow

TaxonomyResolver = Callable[[str, str | None], tuple[str, str | None] | None]
GENERIC_NORMALIZATION_VERSION = "generic-normalization-v1"

ALIASES = {
    "transaction_date": (
        "transaction date",
        "date",
        "datum transakcije",
        "datum knjiženja",
        "datum bremenitve",
        "datum",
        "booking date",
        "value date",
    ),
    "transaction_timestamp": (
        "transaction timestamp",
        "timestamp",
        "completed date",
        "started date",
        "created at",
        "date time",
        "datetime",
    ),
    "description": (
        "description",
        "details",
        "merchant",
        "payee",
        "recipient",
        "prejemnik",
        "prodajno mesto",
        "opis",
        "narrative",
        "memo",
    ),
    "amount": (
        "amount",
        "transaction amount",
        "znesek",
        "value",
        "net amount",
    ),
    "debit": ("debit", "debit amount", "charge", "breme", "odhodki", "withdrawal"),
    "credit": ("credit", "credit amount", "payment", "dobro", "prilivi", "deposit"),
    "currency": ("currency", "valuta", "currency code", "ccy"),
    "source_native_id": (
        "transaction id",
        "id transakcije",
        "reference",
        "referenca",
        "native id",
        "id",
    ),
    "category_hint": ("category", "kategorija", "source category"),
    "subcategory_hint": ("subcategory", "podkategorija", "source subcategory"),
}


class MappingError(ValueError):
    pass


def infer_universal_mapping(
    inspection: ImportInspection,
    *,
    default_currency: str | None = None,
) -> UniversalMappingSpec | None:
    matches = {target: _alias_column(inspection, aliases) for target, aliases in ALIASES.items()}
    description = matches["description"]
    date_column = matches["transaction_date"] or matches["transaction_timestamp"]
    amount_column = matches["amount"]
    debit_column = matches["debit"]
    credit_column = matches["credit"]
    currency_column = matches["currency"]
    if description is None or date_column is None:
        return None
    if amount_column is not None:
        amount = SignedAmount(
            source_column=amount_column,
            number_format=_infer_number_format(inspection, amount_column),
        )
    elif debit_column is not None and credit_column is not None:
        amount = DebitCreditAmount(
            debit_column=debit_column,
            credit_column=credit_column,
            number_format=_infer_number_format(inspection, debit_column, credit_column),
        )
    else:
        return None
    if currency_column is not None:
        currency = SourceCurrency(source_column=currency_column)
    elif default_currency is not None:
        normalized_currency = default_currency.strip().upper()
        currency = ConstantCurrency(value=normalized_currency)
    else:
        return None

    category = matches["category_hint"]
    subcategory = matches["subcategory_hint"] if category is not None else None
    date_format = _infer_date_format(inspection, date_column) if date_column is not None else None
    if date_column is not None and date_format is None:
        return None
    return UniversalMappingSpec(
        transaction_date=DateSource(source_column=date_column, format=date_format)
        if date_column is not None
        else None,
        description=TextSource(source_column=description),
        amount=amount,
        currency=currency,
        source_native_id=_optional_source(matches["source_native_id"]),
        category_hint=_optional_source(category),
        subcategory_hint=_optional_source(subcategory),
    )


def transform_file(
    path: Path,
    inspection: ImportInspection,
    plan: UniversalMappingSpec,
    *,
    max_rows: int = 100_000,
    taxonomy_resolver: TaxonomyResolver | None = None,
) -> list[ParsedRow]:
    rows = read_source_rows(path, inspection, max_rows=max_rows)
    return transform_rows(rows, inspection, plan, taxonomy_resolver=taxonomy_resolver)


def transform_rows(
    rows: Sequence[SourceRow],
    inspection: ImportInspection,
    plan: UniversalMappingSpec,
    *,
    taxonomy_resolver: TaxonomyResolver | None = None,
) -> list[ParsedRow]:
    _validate_plan_columns(plan, inspection)
    header_values = {column.id: column.raw_label for column in inspection.columns}
    transformed = []
    for row in rows:
        raw = dict(row.values)
        audit_reason = _audit_reason(row, raw, header_values, plan)
        if audit_reason is not None:
            transformed.append(_audit_row(row.row_number, raw, audit_reason))
            continue
        try:
            transformed.append(_transform_row(row, raw, plan, taxonomy_resolver))
        except (MappingError, ValueError, TypeError, OverflowError) as exc:
            transformed.append(_error_row(row.row_number, raw, str(exc)))
    return transformed


def generic_row_fingerprint(
    structural_signature: str,
    raw: Mapping[str, Any],
    *,
    normalization_version: str = GENERIC_NORMALIZATION_VERSION,
) -> str:
    cells = [
        [column_id, normalized]
        for column_id in sorted(raw)
        if (normalized := _normalize_fingerprint_value(raw[column_id])) is not None
    ]
    payload = {
        "algorithm": "generic-row-v1",
        "structural_signature": structural_signature,
        "normalization_version": normalization_version,
        "cells": cells,
    }
    encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def _transform_row(
    row: SourceRow,
    raw: dict[str, Any],
    plan: UniversalMappingSpec,
    taxonomy_resolver: TaxonomyResolver | None,
) -> ParsedRow:
    transaction_at = (
        _parse_timestamp(
            _required(raw, plan.transaction_timestamp.source_column),
            plan.transaction_timestamp,
        )
        if plan.transaction_timestamp is not None
        else None
    )
    transaction_date = (
        _parse_date(_required(raw, plan.transaction_date.source_column), plan.transaction_date)
        if plan.transaction_date is not None
        else transaction_at.date()
        if transaction_at is not None
        else None
    )
    if transaction_at is not None and transaction_date != transaction_at.date():
        raise MappingError("transaction date differs from timestamp-derived date")
    description = _text(_required(raw, plan.description.source_column), plan.description)
    if not description:
        raise MappingError("description is blank")
    amount_minor = _amount_minor(raw, plan.amount)
    if amount_minor == 0:
        raise MappingError("amount must not be zero")
    currency = _currency(raw, plan.currency)
    source_native_id = _optional_text(raw, plan.source_native_id)
    category_value = _optional_text(raw, plan.category_hint)
    subcategory_value = _optional_text(raw, plan.subcategory_hint)
    category_id = subcategory_id = None
    if category_value and taxonomy_resolver is not None:
        resolved = taxonomy_resolver(category_value, subcategory_value)
        if resolved is not None:
            category_id, subcategory_id = resolved
            if subcategory_value and subcategory_id is None:
                category_id = None
    kind = TransactionKind.INCOME if amount_minor > 0 else TransactionKind.EXPENSE
    return ParsedRow(
        row_number=row.row_number,
        raw=raw,
        transaction_date=transaction_date,
        transaction_at=transaction_at,
        description=description,
        amount_minor=amount_minor,
        currency=currency,
        kind=kind,
        source_native_id=source_native_id,
        category_id=category_id,
        subcategory_id=subcategory_id,
    )


def _audit_reason(
    row: SourceRow,
    raw: Mapping[str, Any],
    header: Mapping[str, Any],
    plan: UniversalMappingSpec,
) -> str | None:
    reason = None
    if plan.row_bounds.first_row is not None and row.row_number < plan.row_bounds.first_row:
        reason = "row is before the confirmed data bound"
    elif plan.row_bounds.last_row is not None and row.row_number > plan.row_bounds.last_row:
        reason = "row is after the confirmed data bound"
    elif plan.skip_empty_rows and all(_is_blank(value) for value in raw.values()):
        reason = "empty source row"
    elif plan.skip_repeated_headers and all(
        normalize_label(raw.get(column_id)) == normalize_label(label)
        for column_id, label in header.items()
    ):
        reason = "exact repeated header row"
    elif plan.footer_rule is not None:
        marker = normalize_label(raw.get(plan.footer_rule.source_column))
        if marker == plan.footer_rule.normalized_value:
            reason = "confirmed footer row"
    if reason is not None:
        return reason
    for exact_filter in plan.exact_filters:
        value = _normalized_exact(raw.get(exact_filter.source_column))
        matches = value in exact_filter.values
        if exact_filter.mode == "include" and not matches:
            return "row does not match the exact inclusion filter"
        if exact_filter.mode == "exclude" and matches:
            return "row matches the exact exclusion filter"
    return None


def _amount_minor(raw: Mapping[str, Any], mapping: SignedAmount | DebitCreditAmount) -> int:
    if isinstance(mapping, SignedAmount):
        amount = _parse_decimal(_required(raw, mapping.source_column), mapping.number_format)
        if mapping.expense_sign_convention == ExpenseSignConvention.EXPENSES_POSITIVE:
            amount = -amount
        return _decimal_to_minor(amount)
    debit_raw = raw.get(mapping.debit_column)
    credit_raw = raw.get(mapping.credit_column)
    debit_present = not _is_blank(debit_raw)
    credit_present = not _is_blank(credit_raw)
    if debit_present and credit_present:
        raise MappingError("row contains both debit and credit amounts")
    if not debit_present and not credit_present:
        raise MappingError("debit and credit amounts are blank")
    if debit_present:
        debit = _parse_decimal(debit_raw, mapping.number_format)
        _validate_source_sign(debit, mapping.debit_source_sign, "debit")
        return -abs(_decimal_to_minor(debit))
    credit = _parse_decimal(credit_raw, mapping.number_format)
    _validate_source_sign(credit, mapping.credit_source_sign, "credit")
    return abs(_decimal_to_minor(credit))


def _parse_decimal(value: Any, number_format: NumberFormat) -> Decimal:  # noqa: PLR0912
    if isinstance(value, bool) or value is None:
        raise MappingError("amount is missing")
    if isinstance(value, int | float | Decimal):
        if isinstance(value, float) and not math.isfinite(value):
            raise MappingError("amount is not finite")
        return Decimal(str(value))
    text = unicodedata.normalize("NFKC", str(value)).strip()
    negative_parentheses = text.startswith("(") and text.endswith(")")
    if negative_parentheses:
        if not number_format.allow_parentheses:
            raise MappingError("parenthesized amount is not enabled")
        text = text[1:-1].strip()
    trailing_minus = text.endswith("-")
    if trailing_minus:
        if not number_format.allow_trailing_minus:
            raise MappingError("trailing-minus amount is not enabled")
        text = text[:-1].strip()
    if number_format.strip_currency_symbols:
        text = re.sub(r"^[^\d+\-(]+|[^\d.,'\s)]+$", "", text).strip()
    if number_format.thousands_separator is not None:
        text = text.replace(number_format.thousands_separator, "")
    if number_format.decimal_separator != ".":
        text = text.replace(number_format.decimal_separator, ".")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", text):
        raise MappingError("amount does not match the configured number format")
    try:
        amount = Decimal(text)
    except InvalidOperation as exc:
        raise MappingError("amount is invalid") from exc
    if negative_parentheses or trailing_minus:
        if amount < 0:
            raise MappingError("amount contains conflicting negative signs")
        amount = -amount
    return amount


def _decimal_to_minor(value: Decimal) -> int:
    minor = (value * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return int(minor)


def _validate_source_sign(value: Decimal, convention: str, field: str) -> None:
    if value == 0:
        raise MappingError(f"{field} amount must not be zero")
    if convention == "positive" and value < 0:
        raise MappingError(f"{field} amount has a contrary sign")
    if convention == "negative" and value > 0:
        raise MappingError(f"{field} amount has a contrary sign")


def _parse_date(value: Any, source: DateSource) -> date:
    parsed = _parse_datetime(value, source.format)
    return parsed.date()


def _parse_timestamp(value: Any, source: TimestampSource) -> datetime:
    parsed = _parse_datetime(value, source.format)
    try:
        timezone = ZoneInfo(source.timezone)
    except ZoneInfoNotFoundError as exc:
        raise MappingError("timestamp timezone is unknown") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone)
    return parsed.astimezone(timezone)


def _parse_datetime(value: Any, explicit_format: str) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    text = str(value).strip()
    if not text:
        raise MappingError("date or timestamp is blank")
    try:
        return datetime.strptime(text, explicit_format)
    except ValueError as exc:
        raise MappingError("date does not match the configured format") from exc


def _currency(raw: Mapping[str, Any], mapping: SourceCurrency | ConstantCurrency) -> str:
    value = (
        mapping.value if isinstance(mapping, ConstantCurrency) else raw.get(mapping.source_column)
    )
    currency = str(value or "").strip().upper()
    if currency not in ISO_CURRENCY_CODES:
        raise MappingError("currency must be an ISO 4217 code")
    return currency


def _text(value: Any, mapping: TextSource) -> str:
    text = unicodedata.normalize("NFKC", str(value))
    if mapping.strip:
        text = text.strip()
    if mapping.collapse_whitespace:
        text = " ".join(text.split())
    return text


def _optional_text(raw: Mapping[str, Any], mapping: OptionalTextSource | None) -> str | None:
    if mapping is None or _is_blank(raw.get(mapping.source_column)):
        return None
    return str(raw[mapping.source_column]).strip() or None


def _required(raw: Mapping[str, Any], column_id: str) -> Any:
    value = raw.get(column_id)
    if _is_blank(value):
        raise MappingError(f"required source column {column_id} is blank")
    return value


def _validate_plan_columns(plan: UniversalMappingSpec, inspection: ImportInspection) -> None:
    available = {column.id for column in inspection.columns}
    referenced = {
        plan.description.source_column,
        *(item.source_column for item in plan.exact_filters),
    }
    for optional in (
        plan.transaction_date,
        plan.transaction_timestamp,
        plan.source_native_id,
        plan.category_hint,
        plan.subcategory_hint,
        plan.footer_rule,
    ):
        if optional is not None:
            referenced.add(optional.source_column)
    if isinstance(plan.amount, SignedAmount):
        referenced.add(plan.amount.source_column)
    else:
        referenced.update((plan.amount.debit_column, plan.amount.credit_column))
    if isinstance(plan.currency, SourceCurrency):
        referenced.add(plan.currency.source_column)
    missing = sorted(referenced - available)
    if missing:
        raise MappingError(f"mapping references unknown source columns: {', '.join(missing)}")


def _audit_row(row_number: int, raw: dict[str, Any], reason: str) -> ParsedRow:
    return ParsedRow(
        row_number=row_number,
        raw=raw,
        transaction_date=None,
        transaction_at=None,
        description=None,
        amount_minor=None,
        currency=None,
        kind=None,
        disposition=StagedDisposition.AUDIT_ONLY,
        ignore_reason=reason,
        issues=[{"code": "source_row_filtered", "message": reason}],
    )


def _error_row(row_number: int, raw: dict[str, Any], message: str) -> ParsedRow:
    return ParsedRow(
        row_number=row_number,
        raw=raw,
        transaction_date=None,
        transaction_at=None,
        description=None,
        amount_minor=None,
        currency=None,
        kind=None,
        disposition=StagedDisposition.PENDING,
        issues=[{"code": "parse_error", "message": message}],
    )


def _alias_column(inspection: ImportInspection, aliases: Sequence[str]) -> str | None:
    alias_rank = {normalize_label(alias): rank for rank, alias in enumerate(aliases)}
    candidates = [
        (alias_rank[column.normalized_label], column.position, column.id)
        for column in inspection.columns
        if column.normalized_label in alias_rank
    ]
    return min(candidates)[2] if candidates else None


def _infer_number_format(inspection: ImportInspection, *column_ids: str) -> NumberFormat:
    values = [
        str(row.values.get(column_id) or "")
        for row in inspection.preview
        for column_id in column_ids
        if not _is_blank(row.values.get(column_id))
    ]
    decimal_separator = "."
    thousands_separator = None
    comma_decimal = sum(bool(re.search(r",\d{1,4}\D*$", value)) for value in values)
    dot_decimal = sum(bool(re.search(r"\.\d{1,4}\D*$", value)) for value in values)
    if comma_decimal > dot_decimal:
        decimal_separator = ","
        if any("." in value for value in values):
            thousands_separator = "."
    elif any("," in value for value in values):
        thousands_separator = ","
    elif any(" " in value.strip() for value in values):
        thousands_separator = " "
    return NumberFormat(
        decimal_separator=decimal_separator,
        thousands_separator=thousands_separator,
        allow_parentheses=any(value.strip().startswith("(") for value in values),
        allow_trailing_minus=any(value.strip().endswith("-") for value in values),
    )


def _infer_date_format(inspection: ImportInspection, column_id: str) -> str | None:
    matches = [
        candidates
        for row in inspection.preview
        if not _is_blank(value := row.values.get(column_id))
        if (candidates := _date_formats(value))
    ]
    if not matches:
        return None
    formats = set.intersection(*matches)
    return formats.pop() if len(formats) == 1 else None


def _date_formats(value: Any) -> set[str]:
    if isinstance(value, datetime):
        return {"%Y-%m-%d %H:%M:%S"}
    if isinstance(value, date):
        return {"%Y-%m-%d"}
    text = str(value).strip()
    candidates = (
        "%Y-%m-%d",
        "%Y/%m/%d",
        "%d/%m/%Y",
        "%d.%m.%Y",
        "%d-%m-%Y",
        "%m/%d/%Y",
        "%Y%m%d",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%d/%m/%Y %H:%M:%S",
        "%d/%m/%Y %H:%M",
    )
    matches = set()
    for candidate in candidates:
        try:
            candidate_text = text.replace("Z", "+0000") if candidate.endswith("%z") else text
            datetime.strptime(candidate_text, candidate)
        except ValueError:
            continue
        matches.add(candidate)
    return matches


def _optional_source(column_id: str | None) -> OptionalTextSource | None:
    return OptionalTextSource(source_column=column_id) if column_id is not None else None


def _normalized_exact(value: Any) -> str:
    return " ".join(str(value or "").casefold().split())


def _is_blank(value: Any) -> bool:
    return (
        value is None or (isinstance(value, float) and math.isnan(value)) or not str(value).strip()
    )


def _normalize_fingerprint_value(value: Any) -> str | int | float | bool | None:
    if _is_blank(value):
        return None
    if isinstance(value, bool | int):
        return value
    if isinstance(value, float):
        return format(Decimal(str(value)), "f")
    if isinstance(value, datetime | date):
        return value.isoformat()
    return " ".join(unicodedata.normalize("NFKC", str(value)).strip().split())
