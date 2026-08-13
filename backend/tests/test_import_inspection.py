import zipfile
from pathlib import Path

import pytest
from openpyxl import Workbook

from backend.app.imports.inspection import InspectionError, inspect_file, read_source_rows
from backend.app.imports.models import ImportFileType


def test_csv_inspection_is_content_based_and_preserves_positional_headers(
    tmp_path: Path,
) -> None:
    first = tmp_path / "statement.xlsx"
    first.write_text(
        "report generated today;;;;\n"
        "Date;Description;Amount;;Amount\n"
        '01.08.2026;"Coffee; beans";-4,50;;EUR 4,50\n'
        ";;;;\n"
        "Date;Description;Amount;;Amount\n"
        "Total;;;;\n",
        encoding="utf-8",
    )

    inspection = inspect_file(first, header_row=2, preview_limit=100)

    assert inspection.file_type == ImportFileType.CSV
    assert inspection.delimiter == ";"
    assert inspection.header_row == 2
    assert [column.id for column in inspection.columns] == [
        "c000",
        "c001",
        "c002",
        "c003",
        "c004",
    ]
    assert [column.raw_label for column in inspection.columns] == [
        "Date",
        "Description",
        "Amount",
        "",
        "Amount",
    ]
    assert inspection.blank_rows == (4,)
    assert inspection.repeated_header_rows == (5,)
    assert inspection.possible_footer_rows == (6,)
    assert inspection.preview[0].values["c001"] == "Coffee; beans"
    assert inspection.preview[0].values["c002"] == "-4,50"

    second = tmp_path / "renamed.csv"
    second.write_text(
        "different preamble;;;;\n"
        "Date;Description;Amount;;Amount\n"
        "02.08.2026;Different merchant;-9000,00;;EUR 9000,00\n",
        encoding="utf-8",
    )
    second_inspection = inspect_file(second, header_row=2)
    assert second_inspection.structural_signature == inspection.structural_signature


def test_csv_preview_is_bounded_and_source_rows_retain_physical_numbers(tmp_path: Path) -> None:
    path = tmp_path / "many.csv"
    path.write_text(
        "date,description,amount\n"
        + "".join(f"2026-08-{index:02d},Item {index},-{index}\n" for index in range(1, 26)),
        encoding="utf-8",
    )

    inspection = inspect_file(path, preview_offset=10, preview_limit=5)
    rows = read_source_rows(path, inspection)

    assert len(inspection.preview) == 5
    assert inspection.preview[0].row_number == 12
    assert len(rows) == 25
    assert rows[0].row_number == 2
    assert rows[-1].row_number == 26
    with pytest.raises(InspectionError, match="preview_limit"):
        inspect_file(path, preview_limit=101)


def test_xlsx_sheet_and_header_selection_reads_cached_values_only(tmp_path: Path) -> None:
    path = tmp_path / "workbook.bin"
    workbook = Workbook()
    cover = workbook.active
    cover.title = "Cover"
    cover.append(["Statement"])
    transactions = workbook.create_sheet("Transactions")
    transactions.append(["Account export"])
    transactions.append([None])
    transactions.append(["Datum", "Opis", "Znesek"])
    transactions.append(["01.08.2026", "Coffee", "=1+1"])
    workbook.save(path)

    inspection = inspect_file(path, sheet="Transactions", header_row=3)

    assert inspection.file_type == ImportFileType.XLSX
    assert [sheet.name for sheet in inspection.sheets] == ["Cover", "Transactions"]
    assert inspection.selected_sheet == "Transactions"
    assert inspection.header_row == 3
    assert inspection.preview[0].values["c002"] is None


def test_xlsx_rejects_macros_external_links_and_malformed_archives(tmp_path: Path) -> None:
    macro = tmp_path / "macro.xlsx"
    with zipfile.ZipFile(macro, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/vbaProject.bin", b"macro")
    with pytest.raises(InspectionError, match="macros"):
        inspect_file(macro)

    external = tmp_path / "external.xlsx"
    with zipfile.ZipFile(external, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("xl/workbook.xml", "<workbook/>")
        archive.writestr("xl/externalLinks/externalLink1.xml", "<externalLink/>")
    with pytest.raises(InspectionError, match="external links"):
        inspect_file(external)

    malformed = tmp_path / "malformed.xlsx"
    malformed.write_bytes(b"PK\x03\x04not-a-valid-archive")
    with pytest.raises(InspectionError, match="malformed"):
        inspect_file(malformed)


def test_inspection_enforces_column_and_row_limits(tmp_path: Path) -> None:
    too_wide = tmp_path / "wide.csv"
    too_wide.write_text(
        ",".join(f"column-{index}" for index in range(257)) + "\n",
        encoding="utf-8",
    )
    with pytest.raises(InspectionError, match="256 columns"):
        inspect_file(too_wide)

    too_long = tmp_path / "long.csv"
    too_long.write_text("date,amount\n1,1\n2,2\n", encoding="utf-8")
    with pytest.raises(InspectionError, match="1 data rows"):
        inspect_file(too_long, max_rows=1)
