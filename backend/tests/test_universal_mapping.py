from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError

from backend.app.database.models import StagedDisposition, TransactionKind
from backend.app.imports.inspection import inspect_file, read_source_rows
from backend.app.imports.mapping import (
    MappingError,
    generic_row_fingerprint,
    infer_universal_mapping,
    transform_rows,
)
from backend.app.imports.models import (
    ConstantCurrency,
    DateSource,
    DebitCreditAmount,
    ExactValueFilter,
    ExpenseSignConvention,
    FooterRule,
    NumberFormat,
    OptionalTextSource,
    SignedAmount,
    SourceCurrency,
    TextSource,
    TimestampSource,
    UniversalMappingSpec,
)


def _inspection(tmp_path: Path, content: str):
    path = tmp_path / "source.csv"
    path.write_text(content, encoding="utf-8")
    return path, inspect_file(path)


def test_universal_mapping_is_strict_and_structurally_valid() -> None:
    with pytest.raises(ValidationError, match="extra_forbidden"):
        UniversalMappingSpec.model_validate(
            {
                "plan_type": "universal",
                "transaction_date": {"source_column": "c000", "format": "%Y-%m-%d"},
                "description": {"source_column": "c001"},
                "amount": {"kind": "signed", "source_column": "c002"},
                "currency": {"kind": "constant", "value": "EUR"},
                "arbitrary_expression": "amount * -1",
            }
        )
    with pytest.raises(ValidationError, match="literal_error"):
        UniversalMappingSpec.model_validate(
            {
                "plan_type": "adapter",
                "schema_version": "adapter-v1",
                "profile_id": "revolut",
                "profile_version": "1",
            }
        )
    with pytest.raises(ValidationError, match="Field required"):
        DateSource.model_validate({"source_column": "c000"})
    with pytest.raises(ValidationError, match="unsupported directives"):
        DateSource(source_column="c000", format="%B %d, %Y")
    with pytest.raises(ValidationError, match="debit and credit columns must differ"):
        DebitCreditAmount(debit_column="c002", credit_column="c002")
    with pytest.raises(ValidationError, match="subcategory_hint requires category_hint"):
        UniversalMappingSpec(
            transaction_date=DateSource(source_column="c000", format="%Y-%m-%d"),
            description=TextSource(source_column="c001"),
            amount=SignedAmount(source_column="c002"),
            currency=ConstantCurrency(value="EUR"),
            subcategory_hint=OptionalTextSource(source_column="c003"),
        )


def test_alias_inference_is_deterministic_and_uses_positional_columns(tmp_path: Path) -> None:
    _, inspection = _inspection(
        tmp_path,
        "Datum transakcije,Opis,Breme,Dobro,Valuta,Referenca,Kategorija,Podkategorija\n"
        "01.08.2026,Coffee,4.50,,EUR,abc,Food,Out\n",
    )

    first = infer_universal_mapping(inspection)
    second = infer_universal_mapping(inspection)

    assert first == second
    assert first is not None
    assert first.transaction_date == DateSource(source_column="c000", format="%d.%m.%Y")
    assert first.description.source_column == "c001"
    assert isinstance(first.amount, DebitCreditAmount)
    assert first.amount.debit_column == "c002"
    assert first.amount.credit_column == "c003"
    assert first.source_native_id == OptionalTextSource(source_column="c005")
    assert first.category_hint == OptionalTextSource(source_column="c006")
    assert first.subcategory_hint == OptionalTextSource(source_column="c007")


def test_alias_inference_does_not_guess_ambiguous_slash_dates(tmp_path: Path) -> None:
    _, inspection = _inspection(
        tmp_path,
        "Date,Description,Amount,Currency\n08/09/2026,Coffee,-4.50,EUR\n",
    )

    assert infer_universal_mapping(inspection) is None


def test_datetime_inference_maps_one_date_and_discards_time(tmp_path: Path) -> None:
    path, inspection = _inspection(
        tmp_path,
        "Created At,Description,Amount,Currency\n"
        "2026-08-01T23:30:00,Coffee,-4.50,EUR\n",
    )

    plan = infer_universal_mapping(inspection)

    assert plan is not None
    assert plan.transaction_date == DateSource(
        source_column="c000", format="%Y-%m-%dT%H:%M:%S"
    )
    assert plan.transaction_timestamp is None
    parsed = transform_rows(read_source_rows(path, inspection), inspection, plan)[0]
    assert parsed.transaction_date == date(2026, 8, 1)
    assert parsed.transaction_at is None


def test_signed_amount_date_currency_and_taxonomy_transforms(tmp_path: Path) -> None:
    path, inspection = _inspection(
        tmp_path,
        "When,Details,Value,CCY,Category,Subcategory\n"
        '01.08.2026 23:30,Coffee,"€ 1.234,56-",eur,Food,Out\n',
    )
    rows = read_source_rows(path, inspection)
    plan = UniversalMappingSpec(
        transaction_timestamp=TimestampSource(
            source_column="c000",
            format="%d.%m.%Y %H:%M",
            timezone="Europe/Ljubljana",
        ),
        description=TextSource(source_column="c001"),
        amount=SignedAmount(
            source_column="c002",
            number_format=NumberFormat(
                decimal_separator=",",
                thousands_separator=".",
                allow_trailing_minus=True,
            ),
        ),
        currency=SourceCurrency(source_column="c003"),
        category_hint=OptionalTextSource(source_column="c004"),
        subcategory_hint=OptionalTextSource(source_column="c005"),
    )

    parsed = transform_rows(
        rows,
        inspection,
        plan,
        taxonomy_resolver=lambda category, subcategory: (
            ("food-id", "out-id") if (category, subcategory) == ("Food", "Out") else None
        ),
    )[0]

    assert parsed.transaction_date == date(2026, 8, 1)
    assert parsed.transaction_at is not None
    assert parsed.transaction_at.tzinfo is not None
    assert parsed.description == "Coffee"
    assert parsed.amount_minor == -123456
    assert parsed.currency == "EUR"
    assert parsed.kind == TransactionKind.EXPENSE
    assert parsed.category_id == "food-id"
    assert parsed.subcategory_id == "out-id"


def test_signed_expense_conventions_and_debit_credit_are_deterministic(tmp_path: Path) -> None:
    signed_path, signed_inspection = _inspection(
        tmp_path,
        "Date,Description,Amount\n2026-08-01,Expense,12.34\n2026-08-02,Income,-50.00\n",
    )
    positive_expenses = UniversalMappingSpec(
        transaction_date=DateSource(source_column="c000", format="%Y-%m-%d"),
        description=TextSource(source_column="c001"),
        amount=SignedAmount(
            source_column="c002",
            expense_sign_convention=ExpenseSignConvention.EXPENSES_POSITIVE,
        ),
        currency=ConstantCurrency(value="EUR"),
    )
    signed = transform_rows(
        read_source_rows(signed_path, signed_inspection), signed_inspection, positive_expenses
    )
    assert [(row.amount_minor, row.kind) for row in signed] == [
        (-1234, TransactionKind.EXPENSE),
        (5000, TransactionKind.INCOME),
    ]

    path, inspection = _inspection(
        tmp_path,
        "Date,Description,Debit,Credit\n"
        '2026-08-01,Coffee,"(12.34)",\n'
        "2026-08-02,Salary,,50.00\n"
        "2026-08-03,Conflict,1.00,2.00\n"
        "2026-08-04,Wrong sign,1.00,\n",
    )
    plan = UniversalMappingSpec(
        transaction_date=DateSource(source_column="c000", format="%Y-%m-%d"),
        description=TextSource(source_column="c001"),
        amount=DebitCreditAmount(
            debit_column="c002",
            credit_column="c003",
            debit_source_sign="negative",
            number_format=NumberFormat(allow_parentheses=True),
        ),
        currency=ConstantCurrency(value="EUR"),
    )

    parsed = transform_rows(read_source_rows(path, inspection), inspection, plan)

    assert [(row.amount_minor, row.kind) for row in parsed[:2]] == [
        (-1234, TransactionKind.EXPENSE),
        (5000, TransactionKind.INCOME),
    ]
    assert parsed[2].issues[0]["code"] == "parse_error"
    assert "both debit and credit" in parsed[2].issues[0]["message"]
    assert parsed[3].issues[0]["code"] == "parse_error"


def test_filters_empty_repeated_header_footer_and_errors_remain_as_rows(tmp_path: Path) -> None:
    path, inspection = _inspection(
        tmp_path,
        "Date,Description,Amount,Status\n"
        "2026-08-01,Coffee,-4.50,completed\n"
        "2026-08-02,Pending,-2.00,pending\n"
        ",,,\n"
        "Date,Description,Amount,Status\n"
        "TOTAL,,,\n"
        "bad-date,Broken,nope,completed\n",
    )
    plan = UniversalMappingSpec(
        transaction_date=DateSource(source_column="c000", format="%Y-%m-%d"),
        description=TextSource(source_column="c001"),
        amount=SignedAmount(source_column="c002"),
        currency=ConstantCurrency(value="EUR"),
        exact_filters=(
            ExactValueFilter(source_column="c003", mode="include", values=frozenset({"completed"})),
        ),
        footer_rule=FooterRule(source_column="c000", normalized_value="TOTAL:"),
    )

    parsed = transform_rows(read_source_rows(path, inspection), inspection, plan)

    assert len(parsed) == 6
    assert parsed[0].disposition == StagedDisposition.PENDING
    assert all(row.disposition == StagedDisposition.AUDIT_ONLY for row in parsed[1:5])
    assert "inclusion filter" in parsed[1].ignore_reason
    assert parsed[2].ignore_reason == "empty source row"
    assert parsed[3].ignore_reason == "exact repeated header row"
    assert parsed[4].ignore_reason == "confirmed footer row"
    assert parsed[5].issues[0]["code"] == "parse_error"


def test_date_timestamp_mismatch_zero_and_unknown_columns_are_row_or_plan_errors(
    tmp_path: Path,
) -> None:
    path, inspection = _inspection(
        tmp_path,
        "Date,Timestamp,Description,Amount\n2026-08-01,2026-08-02T00:30:00,Coffee,0\n",
    )
    plan = UniversalMappingSpec(
        transaction_date=DateSource(source_column="c000", format="%Y-%m-%d"),
        transaction_timestamp=TimestampSource(
            source_column="c001", format="%Y-%m-%dT%H:%M:%S", timezone="UTC"
        ),
        description=TextSource(source_column="c002"),
        amount=SignedAmount(source_column="c003"),
        currency=ConstantCurrency(value="EUR"),
    )
    parsed = transform_rows(read_source_rows(path, inspection), inspection, plan)[0]
    assert "differs" in parsed.issues[0]["message"]

    invalid_plan = plan.model_copy(update={"description": TextSource(source_column="c999")})
    with pytest.raises(MappingError, match="c999"):
        transform_rows(read_source_rows(path, inspection), inspection, invalid_plan)


def test_generic_fingerprint_is_stable_and_mapping_independent() -> None:
    raw = {"c000": " 2026-08-01 ", "c001": "Coffee", "c002": "", "c003": -4.5}
    same = {"c003": -4.5, "c002": None, "c001": "Coffee", "c000": "2026-08-01"}

    first = generic_row_fingerprint("a" * 64, raw)
    second = generic_row_fingerprint("a" * 64, same)

    assert first == second
    assert len(first) == 64
    assert generic_row_fingerprint("b" * 64, raw) != first
    assert generic_row_fingerprint("a" * 64, {**raw, "c001": "Tea"}) != first
