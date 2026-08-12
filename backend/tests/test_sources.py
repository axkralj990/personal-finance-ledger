from pathlib import Path

import pandas as pd
import pytest

from backend.app.database.models import StagedDisposition, TransactionKind
from backend.app.sources.adapters import DbsAdapter, MastercardAdapter, RevolutAdapter
from backend.app.sources.normalization import amount_to_minor


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12.34", 1234),
        ("-0.005", -1),
        ("1,25", 125),
        ("1.234,56", 123456),
        (2, 200),
    ],
)
def test_amount_to_minor_uses_decimal_rounding(raw: object, expected: int) -> None:
    assert amount_to_minor(raw) == expected


def test_revolut_derives_kinds_from_amount_and_keeps_reverted_rows(tmp_path: Path) -> None:
    statement = tmp_path / "revolut.csv"
    statement.write_text(
        "Type,Started Date,Completed Date,Description,Amount,Fee,Currency,State\n"
        "CARD_PAYMENT,2026-01-01 10:00:00,2026-01-01 10:01:00,Cafe,-4.50,0,EUR,COMPLETED\n"
        "TRANSFER,2026-01-02 10:00:00,2026-01-02 10:00:00,Top up,50,0,EUR,COMPLETED\n"
        "CARD_PAYMENT,2026-01-03 10:00:00,2026-01-03 10:00:00,Refund from shop,8,0,EUR,COMPLETED\n"
        "FEE,2026-01-04 10:00:00,2026-01-04 10:00:00,Service,-1,0,EUR,COMPLETED\n"
        "CARD_PAYMENT,2026-01-05 10:00:00,2026-01-05 10:00:00,Reverted,-9,0,EUR,REVERTED\n",
        encoding="utf-8",
    )

    rows = RevolutAdapter().parse(statement, "EUR", 10)

    assert [row.kind for row in rows] == [
        TransactionKind.EXPENSE,
        TransactionKind.INCOME,
        TransactionKind.INCOME,
        TransactionKind.EXPENSE,
        TransactionKind.EXPENSE,
    ]
    assert rows[-1].disposition == StagedDisposition.AUDIT_ONLY
    assert rows[0].raw["Description"] == "Cafe"


def test_revolut_only_treats_normalized_completed_state_as_eligible(tmp_path: Path) -> None:
    statement = tmp_path / "revolut-states.csv"
    statement.write_text(
        "Started Date,Completed Date,Description,Amount,Currency,State\n"
        "2026-01-01,2026-01-01,Cafe,-4.50,EUR, completed \n"
        "2026-01-02,,Pending,-5.00,EUR,PENDING\n",
        encoding="utf-8",
    )

    rows = RevolutAdapter().parse(statement, "EUR", 10)

    assert rows[0].disposition == StagedDisposition.PENDING
    assert rows[0].issues == []
    assert rows[1].disposition == StagedDisposition.AUDIT_ONLY
    assert rows[1].ignore_reason == "Revolut transaction state is PENDING"


@pytest.mark.parametrize("adapter", [DbsAdapter(), MastercardAdapter()])
def test_debit_credit_columns_treat_zero_as_empty_and_normalize_signs(
    tmp_path: Path, adapter
) -> None:
    statement = tmp_path / "debit-credit.csv"
    statement.write_text(
        "Date,Description,Amount,Debit,Credit,Currency\n"
        "01/02/2026,Coffee,999,4.50,0,EUR\n"
        "02/02/2026,Refund,999,0,8.25,EUR\n",
        encoding="utf-8",
    )

    rows = adapter.parse(statement, "EUR", 10)

    assert [row.amount_minor for row in rows] == [-450, 825]
    assert all(row.issues == [] for row in rows)


def test_mastercard_slovenian_csv_and_excel_use_debit_date_and_negative_expenses(
    tmp_path: Path,
) -> None:
    values = {
        "Prodajno mesto": "PE KRANJ insurance",
        "Št. kartice": "521697******3833",
        "Datum plačila": "22.01.2026",
        "Znesek": 114.87,
        "Valuta": "EUR",
        "Originalna valuta": "EUR",
        "Datum bremenitve": "18.07.2026",
        "Obroki": "6/10",
    }
    csv_path = tmp_path / "mastercard.csv"
    pd.DataFrame([{**values, "": None}]).to_csv(csv_path, index=False)
    excel_path = tmp_path / "mastercard.xlsx"
    pd.DataFrame([{**values, "Unnamed: 8": None}]).to_excel(excel_path, index=False)

    csv_row = MastercardAdapter().parse(csv_path, "EUR", 10)[0]
    excel_row = MastercardAdapter().parse(excel_path, "EUR", 10)[0]

    for row in (csv_row, excel_row):
        assert row.transaction_date.isoformat() == "2026-07-18"
        assert row.amount_minor == -11487
        assert row.kind == TransactionKind.EXPENSE
        assert row.currency == "EUR"
        assert row.description == "PE KRANJ insurance"
        assert row.raw["Datum plačila"]
        assert all(key and not key.casefold().startswith("unnamed") for key in row.raw)
    assert csv_row.source_native_id == excel_row.source_native_id


def test_mastercard_statement_forces_negative_amounts_and_distinguishes_installments(
    tmp_path: Path,
) -> None:
    statement = tmp_path / "mastercard.csv"
    statement.write_text(
        "Prodajno mesto,Št. kartice,Datum plačila,Znesek,Valuta,Originalna valuta,"
        "Datum bremenitve,Obroki\n"
        "Installment,521697******3833,22.01.2026,-1.4,EUR,EUR,18.02.2026,1/10\n"
        "Installment,521697******3833,22.01.2026,1.4,EUR,EUR,18.03.2026,2/10\n",
        encoding="utf-8",
    )

    rows = MastercardAdapter().parse(statement, "EUR", 10)

    assert [row.amount_minor for row in rows] == [-140, -140]
    assert [row.transaction_date.isoformat() for row in rows] == ["2026-02-18", "2026-03-18"]
    assert rows[0].source_native_id != rows[1].source_native_id
