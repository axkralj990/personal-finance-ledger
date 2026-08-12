from __future__ import annotations

import csv
import hashlib
from datetime import date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from backend.app.database.models import Provider, StagedDisposition, TransactionKind
from backend.app.problems import Problem
from backend.app.sources.base import ParsedRow, SourceAdapter
from backend.app.sources.normalization import (
    amount_to_minor,
    json_value,
    normalize_description,
    normalize_header,
)


def _kind(amount_minor: int) -> TransactionKind:
    return TransactionKind.INCOME if amount_minor > 0 else TransactionKind.EXPENSE


def _date(value: Any, *, day_first: bool = False) -> tuple[date, datetime | None]:
    timestamp = pd.to_datetime(value, dayfirst=day_first, errors="raise").to_pydatetime()
    has_time = not (timestamp.hour == timestamp.minute == timestamp.second == 0)
    return timestamp.date(), timestamp if has_time else None


def _columns(row: dict[str, Any]) -> dict[str, Any]:
    return {normalize_header(str(key)): value for key, value in row.items()}


def _value(columns: dict[str, Any], aliases: tuple[str, ...], *, required: bool = True) -> Any:
    for alias in aliases:
        key = normalize_header(alias)
        if key in columns:
            value = columns[key]
            if value is not None and not pd.isna(value) and str(value).strip():
                return value
    if required:
        raise ValueError(f"missing column: {aliases[0]}")
    return None


class CsvAdapter(SourceAdapter):
    parser_version = "1"

    def read(self, path: Path) -> list[dict[str, Any]]:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            return list(csv.DictReader(stream))


class LegacyAdapter(CsvAdapter):
    def parse(self, path: Path, default_currency: str, max_rows: int) -> list[ParsedRow]:
        raw_rows = self.read(path)
        _check_row_limit(raw_rows, max_rows)
        parsed = []
        for row_number, raw in enumerate(raw_rows, start=2):
            columns = _columns(raw)
            original_source = str(columns.get("source", "")).strip()
            normalized_source = LEGACY_SOURCE_ALIASES.get(original_source.casefold(), "legacy")
            preserved_raw = dict(raw)
            preserved_raw["_normalized_source"] = normalized_source
            parsed_row = _parse_standard_row(
                row_number,
                preserved_raw,
                columns,
                default_currency,
                date_aliases=("date",),
                amount_aliases=("amount",),
                description_aliases=("description",),
                legacy_category=str(columns.get("category", "")),
                legacy_subcategory=str(columns.get("subcategory", "")),
            )
            parsed_row.legacy_source = normalized_source
            parsed.append(parsed_row)
        return parsed


class MastercardAdapter(CsvAdapter):
    parser_version = "2"

    def parse(self, path: Path, default_currency: str, max_rows: int) -> list[ParsedRow]:
        if path.suffix.casefold() in {".xls", ".xlsx"}:
            raw_rows = pd.read_excel(path).to_dict(orient="records")
        else:
            raw_rows = self.read(path)
        _check_row_limit(raw_rows, max_rows)
        parsed = []
        identity_occurrences: dict[str, int] = {}
        for row_number, raw in enumerate(raw_rows, start=2):
            cleaned_raw = _without_empty_spreadsheet_columns(raw)
            columns = _columns(cleaned_raw)
            if "prodajnomesto" in columns and "znesek" in columns:
                parsed_row = _parse_mastercard_statement_row(
                    row_number, cleaned_raw, columns, default_currency
                )
                if parsed_row.source_native_id:
                    occurrence = identity_occurrences.get(parsed_row.source_native_id, 0) + 1
                    identity_occurrences[parsed_row.source_native_id] = occurrence
                    parsed_row.source_native_id = f"{parsed_row.source_native_id}:{occurrence}"
                parsed.append(parsed_row)
                continue
            parsed.append(
                _parse_standard_row(
                    row_number,
                    cleaned_raw,
                    columns,
                    default_currency,
                    date_aliases=("date", "transaction date", "datum", "datum transakcije"),
                    amount_aliases=("amount", "transaction amount", "znesek"),
                    debit_aliases=("debit", "debit amount", "charge"),
                    credit_aliases=("credit", "credit amount", "payment"),
                    description_aliases=("description", "merchant", "details", "opis"),
                    day_first=True,
                    native_aliases=("transaction id", "reference", "id"),
                )
            )
        return parsed


class RevolutAdapter(CsvAdapter):
    def parse(self, path: Path, default_currency: str, max_rows: int) -> list[ParsedRow]:
        raw_rows = self.read(path)
        _check_row_limit(raw_rows, max_rows)
        result = []
        for row_number, raw in enumerate(raw_rows, start=2):
            columns = _columns(raw)
            try:
                description = str(_value(columns, ("Description",)))
                amount_minor = amount_to_minor(_value(columns, ("Amount",)))
                state = (
                    str(_value(columns, ("State",), required=False) or "UNKNOWN").strip().upper()
                )
                completed = _value(columns, ("Completed Date", "Started Date"))
                transaction_date, transaction_at = _date(completed)
                eligible = state == "COMPLETED"
                disposition = (
                    StagedDisposition.PENDING if eligible else StagedDisposition.AUDIT_ONLY
                )
                reason = None if eligible else f"Revolut transaction state is {state}"
                result.append(
                    ParsedRow(
                        row_number=row_number,
                        raw={key: json_value(value) for key, value in raw.items()},
                        transaction_date=transaction_date,
                        transaction_at=transaction_at,
                        description=description,
                        amount_minor=amount_minor,
                        currency=str(columns.get("currency") or default_currency).upper(),
                        kind=_kind(amount_minor),
                        source_native_id=_optional(columns, ("Transaction ID", "ID")),
                        disposition=disposition,
                        ignore_reason=reason,
                        issues=(
                            []
                            if eligible
                            else [{"code": "ineligible_source_status", "message": reason}]
                        ),
                    )
                )
            except (ValueError, TypeError) as exc:
                result.append(_invalid_row(row_number, raw, str(exc)))
        return result


def _parse_mastercard_statement_row(
    row_number: int,
    raw: dict[str, Any],
    columns: dict[str, Any],
    default_currency: str,
) -> ParsedRow:
    try:
        description = str(_value(columns, ("Prodajno mesto",))).strip()
        source_amount_minor = amount_to_minor(_value(columns, ("Znesek",)))
        amount_minor = -abs(source_amount_minor)
        purchase_date_value = _value(columns, ("Datum plačila",), required=False)
        debit_date_value = _value(columns, ("Datum bremenitve",), required=False)
        ledger_date_value = debit_date_value or _value(columns, ("Datum plačila",))
        transaction_date, _ = _date(ledger_date_value, day_first=True)
        purchase_date = (
            _date(purchase_date_value, day_first=True)[0].isoformat()
            if purchase_date_value is not None
            else ""
        )
        debit_date = (
            _date(debit_date_value, day_first=True)[0].isoformat()
            if debit_date_value is not None
            else transaction_date.isoformat()
        )
        currency = (_optional(columns, ("Valuta", "Currency")) or default_currency).upper()
        card = _optional(columns, ("Št. kartice", "St. kartice")) or ""
        installments = _optional(columns, ("Obroki",)) or ""
        original_currency = _optional(columns, ("Originalna valuta",)) or ""
        identity = "|".join(
            (
                card,
                normalize_description(description),
                purchase_date,
                debit_date,
                str(source_amount_minor),
                currency,
                original_currency.upper(),
                installments,
            )
        )
        return ParsedRow(
            row_number=row_number,
            raw={key: json_value(value) for key, value in raw.items()},
            transaction_date=transaction_date,
            transaction_at=None,
            description=description,
            amount_minor=amount_minor,
            currency=currency,
            kind=TransactionKind.EXPENSE,
            source_native_id=f"mastercard:{hashlib.sha256(identity.encode()).hexdigest()}",
        )
    except (ValueError, TypeError) as exc:
        return _invalid_row(row_number, raw, str(exc))


class DbsAdapter(SourceAdapter):
    parser_version = "1"

    def parse(self, path: Path, default_currency: str, max_rows: int) -> list[ParsedRow]:
        if path.suffix.casefold() in {".xls", ".xlsx"}:
            frame = pd.read_excel(path)
            raw_rows = frame.to_dict(orient="records")
        else:
            with path.open(encoding="utf-8-sig", newline="") as stream:
                raw_rows = list(csv.DictReader(stream))
        _check_row_limit(raw_rows, max_rows)
        return [
            _parse_standard_row(
                row_number,
                raw,
                _columns(raw),
                default_currency,
                date_aliases=(
                    "Datum transakcije",
                    "Transaction date",
                    "Datum knjiženja",
                    "Date",
                ),
                amount_aliases=("Znesek", "Amount", "Transaction amount"),
                debit_aliases=("Debit", "Debit amount", "Breme", "Odhodki"),
                credit_aliases=("Credit", "Credit amount", "Dobro", "Prilivi"),
                description_aliases=("Opis", "Description", "Prejemnik", "Payee"),
                native_aliases=("ID transakcije", "Transaction ID", "Reference", "Referenca"),
                currency_aliases=("Valuta", "Currency"),
                day_first=True,
            )
            for row_number, raw in enumerate(raw_rows, start=2)
        ]


def _parse_standard_row(
    row_number: int,
    raw: dict[str, Any],
    columns: dict[str, Any],
    default_currency: str,
    *,
    date_aliases: tuple[str, ...],
    amount_aliases: tuple[str, ...],
    debit_aliases: tuple[str, ...] = (),
    credit_aliases: tuple[str, ...] = (),
    description_aliases: tuple[str, ...],
    native_aliases: tuple[str, ...] = (),
    currency_aliases: tuple[str, ...] = (),
    day_first: bool = False,
    legacy_category: str | None = None,
    legacy_subcategory: str | None = None,
) -> ParsedRow:
    try:
        description = str(_value(columns, description_aliases))
        amount_minor = _signed_amount_minor(
            columns,
            amount_aliases=amount_aliases,
            debit_aliases=debit_aliases,
            credit_aliases=credit_aliases,
        )
        transaction_date, transaction_at = _date(_value(columns, date_aliases), day_first=day_first)
        currency = _optional(columns, currency_aliases) or default_currency
        return ParsedRow(
            row_number=row_number,
            raw={key: json_value(value) for key, value in raw.items()},
            transaction_date=transaction_date,
            transaction_at=transaction_at,
            description=description,
            amount_minor=amount_minor,
            currency=currency.upper(),
            kind=_kind(amount_minor),
            source_native_id=_optional(columns, native_aliases),
            legacy_category=legacy_category,
            legacy_subcategory=legacy_subcategory,
        )
    except (ValueError, TypeError) as exc:
        return _invalid_row(row_number, raw, str(exc))


def _optional(columns: dict[str, Any], aliases: tuple[str, ...]) -> str | None:
    if not aliases:
        return None
    value = _value(columns, aliases, required=False)
    return str(value).strip() if value is not None else None


def _signed_amount_minor(
    columns: dict[str, Any],
    *,
    amount_aliases: tuple[str, ...],
    debit_aliases: tuple[str, ...],
    credit_aliases: tuple[str, ...],
) -> int:
    debit = _value(columns, debit_aliases, required=False) if debit_aliases else None
    credit = _value(columns, credit_aliases, required=False) if credit_aliases else None
    debit_minor = amount_to_minor(debit) if debit is not None else 0
    credit_minor = amount_to_minor(credit) if credit is not None else 0
    if debit_minor != 0 and credit_minor != 0:
        raise ValueError("row contains both debit and credit amounts")
    if debit_minor != 0:
        return -abs(debit_minor)
    if credit_minor != 0:
        return abs(credit_minor)
    if debit is not None or credit is not None:
        amount = _value(columns, amount_aliases, required=False)
        return amount_to_minor(amount) if amount is not None else 0
    return amount_to_minor(_value(columns, amount_aliases))


def _invalid_row(row_number: int, raw: dict[str, Any], message: str) -> ParsedRow:
    return ParsedRow(
        row_number=row_number,
        raw={key: json_value(value) for key, value in raw.items()},
        transaction_date=None,
        transaction_at=None,
        description=None,
        amount_minor=None,
        currency=None,
        kind=None,
        issues=[{"code": "parse_error", "message": message}],
    )


def _without_empty_spreadsheet_columns(raw: dict[str, Any]) -> dict[str, Any]:
    return {
        str(key): value
        for key, value in raw.items()
        if key is not None
        and (normalized := normalize_header(str(key)))
        and not normalized.startswith("unnamed")
    }


def _check_row_limit(rows: list[dict[str, Any]], max_rows: int) -> None:
    if len(rows) > max_rows:
        raise Problem(413, "row_limit_exceeded", f"File contains more than {max_rows} rows")


ADAPTERS: dict[Provider, type[SourceAdapter]] = {
    Provider.LEGACY: LegacyAdapter,
    Provider.REVOLUT: RevolutAdapter,
    Provider.DBS: DbsAdapter,
    Provider.MASTERCARD: MastercardAdapter,
}

LEGACY_SOURCE_ALIASES = {
    "dbs": "dbs",
    "matercard": "mastercard",
    "mastercard": "mastercard",
    "revolut": "revolut",
    "joint": "joint",
    "cash": "manual",
    "manual": "manual",
}


def adapter_for(provider: Provider) -> SourceAdapter:
    adapter_class = ADAPTERS.get(provider)
    if adapter_class is None:
        raise Problem(422, "unsupported_provider", f"No file adapter for {provider.value}")
    return adapter_class()
