from __future__ import annotations

import re
import unicodedata
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from backend.app.currencies import ISO_CURRENCY_CODES

COLUMN_ID_PATTERN = re.compile(r"^c\d{3}$")
ColumnId = Annotated[str, Field(pattern=COLUMN_ID_PATTERN.pattern)]
CellValue = str | int | float | bool | None


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImportFileType(StrEnum):
    CSV = "CSV"
    XLS = "XLS"
    XLSX = "XLSX"


class InferredValueType(StrEnum):
    EMPTY = "EMPTY"
    TEXT = "TEXT"
    DATE = "DATE"
    TIMESTAMP = "TIMESTAMP"
    NUMBER = "NUMBER"
    CURRENCY = "CURRENCY"
    MIXED = "MIXED"


class InspectedColumn(StrictModel):
    id: ColumnId
    position: int = Field(ge=0, le=255)
    raw_label: str = Field(max_length=1_000)
    normalized_label: str = Field(max_length=1_000)
    inferred_type: InferredValueType


class SourceRow(StrictModel):
    row_number: int = Field(ge=1)
    values: dict[ColumnId, CellValue]


class SheetInspection(StrictModel):
    name: str = Field(min_length=1, max_length=255)
    index: int = Field(ge=0, le=31)
    row_count: int = Field(ge=0)
    column_count: int = Field(ge=0, le=256)
    candidate_header_rows: tuple[int, ...] = Field(default=(), max_length=10)


class ImportInspection(StrictModel):
    inspection_version: Literal["inspection-v1"] = "inspection-v1"
    execution_schema_version: Literal["universal-v1"] = "universal-v1"
    file_type: ImportFileType
    encoding: str | None = Field(default=None, max_length=40)
    delimiter: str | None = Field(default=None, min_length=1, max_length=1)
    quote_character: str | None = Field(default=None, min_length=1, max_length=1)
    sheets: tuple[SheetInspection, ...] = Field(min_length=1, max_length=32)
    selected_sheet: str = Field(min_length=1, max_length=255)
    header_row: int = Field(ge=1)
    data_start_row: int = Field(ge=1)
    data_end_row: int = Field(ge=0)
    row_count: int = Field(ge=0)
    blank_rows: tuple[int, ...] = ()
    repeated_header_rows: tuple[int, ...] = ()
    possible_footer_rows: tuple[int, ...] = ()
    columns: tuple[InspectedColumn, ...] = Field(min_length=1, max_length=256)
    preview_offset: int = Field(default=0, ge=0)
    preview: tuple[SourceRow, ...] = Field(default=(), max_length=100)
    structural_signature: str = Field(min_length=64, max_length=64)

    @model_validator(mode="after")
    def validate_selection(self) -> ImportInspection:
        if self.selected_sheet not in {sheet.name for sheet in self.sheets}:
            raise ValueError("selected_sheet does not exist")
        if self.data_start_row <= self.header_row:
            raise ValueError("data_start_row must follow header_row")
        expected_ids = [f"c{position:03d}" for position in range(len(self.columns))]
        if [column.id for column in self.columns] != expected_ids:
            raise ValueError("columns must use contiguous positional IDs")
        if [column.position for column in self.columns] != list(range(len(self.columns))):
            raise ValueError("column positions must be contiguous")
        return self


class NumberFormat(StrictModel):
    decimal_separator: Literal[".", ","] = "."
    thousands_separator: Literal[",", ".", " ", "\u00a0", "'"] | None = None
    strip_currency_symbols: bool = True
    allow_parentheses: bool = False
    allow_trailing_minus: bool = False

    @model_validator(mode="after")
    def distinct_separators(self) -> NumberFormat:
        if self.decimal_separator == self.thousands_separator:
            raise ValueError("decimal and thousands separators must differ")
        return self


class DateSource(StrictModel):
    source_column: ColumnId
    format: str = Field(min_length=1, max_length=80)

    @field_validator("format")
    @classmethod
    def validate_format(cls, value: str) -> str:
        directives = re.findall(r"%[A-Za-z%]", value)
        if not directives or "%" in re.sub(r"%[A-Za-z%]", "", value):
            raise ValueError("date format contains an invalid directive")
        allowed = {
            "%Y",
            "%y",
            "%m",
            "%d",
            "%H",
            "%I",
            "%M",
            "%S",
            "%f",
            "%p",
            "%z",
            "%%",
        }
        unsupported = sorted(set(directives) - allowed)
        if unsupported:
            raise ValueError(
                f"date format contains unsupported directives: {', '.join(unsupported)}"
            )
        if not ({"%Y", "%y"} & set(directives)) or not {"%m", "%d"} <= set(directives):
            raise ValueError("date format must include year, month, and day")
        return value


class TimestampSource(DateSource):
    timezone: str = Field(default="UTC", min_length=1, max_length=80)


class TextSource(StrictModel):
    source_column: ColumnId
    strip: bool = True
    collapse_whitespace: bool = True


class OptionalTextSource(StrictModel):
    source_column: ColumnId


class ExpenseSignConvention(StrEnum):
    EXPENSES_NEGATIVE = "EXPENSES_NEGATIVE"
    EXPENSES_POSITIVE = "EXPENSES_POSITIVE"


class SignedAmount(StrictModel):
    kind: Literal["signed"] = "signed"
    source_column: ColumnId
    number_format: NumberFormat = NumberFormat()
    expense_sign_convention: ExpenseSignConvention = ExpenseSignConvention.EXPENSES_NEGATIVE


class DebitCreditAmount(StrictModel):
    kind: Literal["debit_credit"] = "debit_credit"
    debit_column: ColumnId
    credit_column: ColumnId
    number_format: NumberFormat = NumberFormat()
    debit_source_sign: Literal["positive", "negative"] = "positive"
    credit_source_sign: Literal["positive", "negative"] = "positive"

    @model_validator(mode="after")
    def distinct_columns(self) -> DebitCreditAmount:
        if self.debit_column == self.credit_column:
            raise ValueError("debit and credit columns must differ")
        return self


AmountMapping = SignedAmount | DebitCreditAmount


class SourceCurrency(StrictModel):
    kind: Literal["source"] = "source"
    source_column: ColumnId


class ConstantCurrency(StrictModel):
    kind: Literal["constant"] = "constant"
    value: str = Field(min_length=3, max_length=3)

    @field_validator("value")
    @classmethod
    def validate_iso_currency(cls, value: str) -> str:
        if value not in ISO_CURRENCY_CODES:
            raise ValueError("currency must be an uppercase ISO 4217 code")
        return value


CurrencyMapping = SourceCurrency | ConstantCurrency


class ExactValueFilter(StrictModel):
    source_column: ColumnId
    mode: Literal["include", "exclude"]
    values: tuple[str, ...] = Field(min_length=1, max_length=50)

    @field_validator("values")
    @classmethod
    def normalize_values(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(" ".join(value.casefold().split()) for value in values)
        if any(not value for value in normalized):
            raise ValueError("filter values cannot be blank")
        if len(set(normalized)) != len(normalized):
            raise ValueError("filter values must be unique after normalization")
        return normalized


class FooterRule(StrictModel):
    source_column: ColumnId
    normalized_value: str = Field(max_length=500)

    @field_validator("normalized_value")
    @classmethod
    def normalize_marker(cls, value: str) -> str:
        value = unicodedata.normalize("NFKC", value).casefold().strip()
        value = " ".join(re.sub(r"[^\w]+", " ", value).split())
        if not value:
            raise ValueError("footer marker cannot be blank")
        return value


class RowBounds(StrictModel):
    first_row: int | None = Field(default=None, ge=1)
    last_row: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def ordered_bounds(self) -> RowBounds:
        if (
            self.first_row is not None
            and self.last_row is not None
            and self.first_row > self.last_row
        ):
            raise ValueError("first_row must not follow last_row")
        return self


class UniversalMappingSpec(StrictModel):
    plan_type: Literal["universal"] = "universal"
    schema_version: Literal["universal-v1"] = "universal-v1"
    transaction_date: DateSource | None = None
    transaction_timestamp: TimestampSource | None = None
    description: TextSource
    amount: AmountMapping
    currency: CurrencyMapping
    source_native_id: OptionalTextSource | None = None
    category_hint: OptionalTextSource | None = None
    subcategory_hint: OptionalTextSource | None = None
    row_bounds: RowBounds = RowBounds()
    exact_filters: tuple[ExactValueFilter, ...] = Field(default=(), max_length=16)
    skip_empty_rows: bool = True
    skip_repeated_headers: bool = True
    footer_rule: FooterRule | None = None

    @model_validator(mode="after")
    def validate_mapping(self) -> UniversalMappingSpec:
        if self.transaction_date is None and self.transaction_timestamp is None:
            raise ValueError("transaction_date or transaction_timestamp is required")
        if self.subcategory_hint is not None and self.category_hint is None:
            raise ValueError("subcategory_hint requires category_hint")
        return self
