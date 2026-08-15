import asyncio
import hashlib
import json
import re
import threading
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal, Protocol

import httpx
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    OpenAIError,
    PermissionDeniedError,
    RateLimitError,
)
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from backend.app.config import Settings
from backend.app.imports.models import (
    ColumnId,
    DateSource,
    ImportFileType,
    ImportInspection,
    InferredValueType,
    InspectedColumn,
    SourceRow,
    UniversalMappingSpec,
)

PROMPT_VERSION = "universal-import-mapping-v2"
MAPPING_SCHEMA_VERSION = "universal-v1"
PAYLOAD_VERSION = "openai-mapping-payload-v1"
MAX_SAMPLE_ROWS = 12

_STATUS_ALLOWLIST = frozenset(
    {"completed", "pending", "reverted", "reversed", "cancelled", "declined"}
)
_CURRENCY_ALLOWLIST = frozenset(
    {
        "AED",
        "ARS",
        "AUD",
        "BGN",
        "BHD",
        "BRL",
        "CAD",
        "CHF",
        "CLP",
        "CNY",
        "COP",
        "CZK",
        "DKK",
        "EGP",
        "EUR",
        "GBP",
        "HKD",
        "HRK",
        "HUF",
        "IDR",
        "ILS",
        "INR",
        "ISK",
        "JPY",
        "KRW",
        "KWD",
        "MAD",
        "MXN",
        "MYR",
        "NOK",
        "NZD",
        "PEN",
        "PHP",
        "PLN",
        "QAR",
        "RON",
        "RSD",
        "RUB",
        "SAR",
        "SEK",
        "SGD",
        "THB",
        "TRY",
        "TWD",
        "UAH",
        "USD",
        "UYU",
        "VND",
        "ZAR",
    }
)
_DATE_PATTERNS = (
    (re.compile(r"^\d{4}-\d{2}-\d{2}$"), "%Y-%m-%d", "YYYY-MM-DD"),
    (re.compile(r"^\d{4}/\d{2}/\d{2}$"), "%Y/%m/%d", "YYYY/MM/DD"),
    (re.compile(r"^\d{2}/\d{2}/\d{4}$"), "%d/%m/%Y", "DD/MM/YYYY"),
    (re.compile(r"^\d{2}\.\d{2}\.\d{4}$"), "%d.%m.%Y", "DD.MM.YYYY"),
    (re.compile(r"^\d{2}-\d{2}-\d{4}$"), "%d-%m-%Y", "DD-MM-YYYY"),
    (re.compile(r"^\d{8}$"), "%Y%m%d", "YYYYMMDD"),
)
_TIMESTAMP_PATTERN = re.compile(
    r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?$"
)
_EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
_IBAN_PATTERN = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9 ]{10,30}$", re.IGNORECASE)
_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",
    re.IGNORECASE,
)
_GROUPED_DIGITS_PATTERN = re.compile(r"^(?:\d[ -]?){8,}\d$")
_ALPHANUMERIC_ID_PATTERN = re.compile(r"^(?=.*[A-Za-z])(?=.*\d)[A-Za-z0-9_-]{6,}$")
_IDENTIFIER_HEADER_TERMS = frozenset(
    {
        "account",
        "account number",
        "card",
        "card number",
        "iban",
        "id",
        "identifier",
        "native id",
        "reference",
        "transaction id",
    }
)
_SEMANTIC_HEADER_TERMS = (
    ("subcategory", frozenset({"subcategory", "sub category"})),
    ("timestamp", frozenset({"timestamp", "datetime", "date time", "booked at"})),
    ("date", frozenset({"date", "booking date", "value date"})),
    ("description", frozenset({"description", "details", "merchant", "payee", "memo"})),
    ("debit", frozenset({"debit", "withdrawal"})),
    ("credit", frozenset({"credit", "deposit"})),
    ("amount", frozenset({"amount", "value"})),
    ("currency", frozenset({"currency", "ccy"})),
    ("status", frozenset({"status", "state"})),
    ("category", frozenset({"category"})),
    ("reference", _IDENTIFIER_HEADER_TERMS),
)
_NUMBER_PATTERN = re.compile(
    r"^[+-]?(?:\d{1,3}(?:[ .,'\u2019]\d{3})+|\d+)(?:[.,]\d+)?-$|"
    r"^[+-]?(?:\d{1,3}(?:[ .,'\u2019]\d{3})+|\d+)(?:[.,]\d+)?$"
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MappingColumn(StrictModel):
    column_id: ColumnId
    header: str
    normalized_header: str
    inferred_type: InferredValueType


class InspectionFacts(StrictModel):
    file_type: ImportFileType
    sheet_index: int = Field(ge=0, le=31)
    header_row: int = Field(ge=1)
    column_count: int = Field(ge=1, le=256)


class MappingSuggestionPayload(StrictModel):
    payload_version: Literal["openai-mapping-payload-v1"] = PAYLOAD_VERSION
    prompt_version: Literal["universal-import-mapping-v2"] = PROMPT_VERSION
    canonical_fields: tuple[str, ...]
    allowed_transformations: tuple[str, ...]
    columns: tuple[MappingColumn, ...]
    representative_rows: tuple[tuple[str, ...], ...]
    inspection: InspectionFacts


class PreparedMappingPayload(StrictModel):
    payload: MappingSuggestionPayload
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class MappingFallbackCode(StrEnum):
    DISABLED = "disabled"
    MISSING_API_KEY = "missing_api_key"
    CONSENT_REQUIRED = "consent_required"
    PAYLOAD_CHANGED = "payload_changed"
    CONCURRENCY_LIMIT = "concurrency_limit"
    LOCAL_RATE_LIMIT = "local_rate_limit"
    AUTHENTICATION = "authentication"
    PERMISSION = "permission"
    CONNECTION = "connection"
    TIMEOUT = "timeout"
    PROVIDER_RATE_LIMIT = "provider_rate_limit"
    PROVIDER_STATUS = "provider_status"
    REFUSAL = "refusal"
    INVALID_RESPONSE = "invalid_response"
    PROVIDER_ERROR = "provider_error"


class MappingFallbackError(StrictModel):
    code: MappingFallbackCode
    message: str
    retryable: bool


class MappingAuditMetadata(StrictModel):
    provider: Literal["openai"] = "openai"
    model: str
    request_id: str | None = None
    prompt_version: Literal["universal-import-mapping-v2"] = PROMPT_VERSION
    schema_version: Literal["universal-v1"] = MAPPING_SCHEMA_VERSION
    payload_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    consented_at: datetime | None
    requested_at: datetime
    duration_ms: int = Field(ge=0)
    outcome: Literal["suggested", "manual_fallback"]
    error_code: MappingFallbackCode | None = None


class MappingSuggestionSuccess(StrictModel):
    status: Literal["suggested"] = "suggested"
    plan: UniversalMappingSpec
    audit: MappingAuditMetadata


class MappingSuggestionFallback(StrictModel):
    status: Literal["manual_fallback"] = "manual_fallback"
    error: MappingFallbackError
    audit: MappingAuditMetadata


MappingSuggestionResult = MappingSuggestionSuccess | MappingSuggestionFallback


class _ResponsesAPI(Protocol):
    async def parse(self, **kwargs: Any) -> Any: ...


class OpenAIClient(Protocol):
    responses: _ResponsesAPI


class _LimitKind(StrEnum):
    CONCURRENCY = "concurrency"
    RATE = "rate"


class _LimitExceededError(Exception):
    def __init__(self, kind: _LimitKind) -> None:
        self.kind = kind
        super().__init__(kind.value)


class InMemoryMappingLimiter:
    def __init__(
        self,
        max_concurrent: int = 1,
        requests_per_hour: int = 10,
        *,
        clock: Any = time.monotonic,
    ) -> None:
        self.max_concurrent = max_concurrent
        self.requests_per_hour = requests_per_hour
        self._clock = clock
        self._active = 0
        self._request_times: list[float] = []
        self._lock = threading.Lock()

    @contextmanager
    def acquire(self) -> Iterator[None]:
        with self._lock:
            now = self._clock()
            self._request_times = [
                request_time for request_time in self._request_times if now - request_time < 3600
            ]
            if self._active >= self.max_concurrent:
                raise _LimitExceededError(_LimitKind.CONCURRENCY)
            if len(self._request_times) >= self.requests_per_hour:
                raise _LimitExceededError(_LimitKind.RATE)
            self._active += 1
            self._request_times.append(now)
        try:
            yield
        finally:
            with self._lock:
                self._active -= 1


_shared_limiters: dict[tuple[int, int], InMemoryMappingLimiter] = {}
_shared_limiters_lock = threading.Lock()


def prepare_mapping_payload(
    inspection: ImportInspection,
    rows: Sequence[SourceRow] | None = None,
) -> PreparedMappingPayload:
    source_rows = inspection.preview if rows is None else rows
    sample_rows = tuple(
        tuple(
            redact_cell(row.values.get(column.id), column=column) for column in inspection.columns
        )
        for row in _representative_rows(source_rows, inspection.columns)
    )
    selected_sheet = next(
        sheet for sheet in inspection.sheets if sheet.name == inspection.selected_sheet
    )
    payload = MappingSuggestionPayload(
        canonical_fields=(
            "transaction_date",
            "description",
            "amount",
            "currency",
            "source_native_id",
            "category_hint",
            "subcategory_hint",
        ),
        allowed_transformations=(
            "explicit date or datetime format with time discarded",
            "decimal and thousands separators",
            "currency-symbol removal",
            "signed amount with EXPENSES_NEGATIVE preserve or EXPENSES_POSITIVE invert",
            "separate debit and credit amounts",
            "constant currency",
            "exact status inclusion or exclusion",
            "empty-row and repeated-header removal",
            "exact footer marker removal",
        ),
        columns=tuple(
            MappingColumn(
                column_id=column.id,
                header=_semantic_header(column),
                normalized_header=_semantic_header(column),
                inferred_type=column.inferred_type,
            )
            for column in inspection.columns
        ),
        representative_rows=sample_rows,
        inspection=InspectionFacts(
            file_type=inspection.file_type,
            sheet_index=selected_sheet.index,
            header_row=inspection.header_row,
            column_count=len(inspection.columns),
        ),
    )
    return PreparedMappingPayload(payload=payload, sha256=payload_sha256(payload))


def canonical_payload_json(payload: MappingSuggestionPayload) -> str:
    return json.dumps(
        payload.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )


def payload_sha256(payload: MappingSuggestionPayload) -> str:
    return hashlib.sha256(canonical_payload_json(payload).encode("utf-8")).hexdigest()


def redact_cell(value: Any, *, column: InspectedColumn | None = None) -> str:
    if _is_empty(value):
        redacted_value = "<EMPTY>"
    elif column is not None and _identifier_column(column):
        redacted_value = "<IDENTIFIER>"
    elif isinstance(value, datetime):
        redacted_value = "<DATETIME:SAMPLE=0000-00-00T00:00:00;FORMAT=%Y-%m-%dT%H:%M:%S>"
    elif isinstance(value, date):
        redacted_value = "<DATE:SAMPLE=0000-00-00;FORMAT=%Y-%m-%d>"
    elif isinstance(value, bool):
        redacted_value = "<TEXT>"
    elif isinstance(value, int | float | Decimal):
        redacted_value = (
            _number_token(str(value)) or "<NUMBER:SIGN=NONE;DECIMAL=NONE;GROUPING=NONE>"
        )
    else:
        redacted_value = _redact_text(str(value).strip())
    return redacted_value


def _identifier_column(column: InspectedColumn) -> bool:
    label = column.normalized_label
    return label in _IDENTIFIER_HEADER_TERMS or any(
        label.endswith(f" {term}") for term in _IDENTIFIER_HEADER_TERMS
    )


def _semantic_header(column: InspectedColumn) -> str:
    label = column.normalized_label
    semantics = [
        semantic
        for semantic, terms in _SEMANTIC_HEADER_TERMS
        if any(
            label == term or label.endswith(f" {term}") or label.startswith(f"{term} ")
            for term in terms
        )
    ]
    return " ".join(dict.fromkeys(semantics)) or "unknown"


def _redact_text(text: str) -> str:
    normalized = text.casefold()
    upper = text.upper()
    pattern_token = _date_token(text)
    if not text:
        return "<EMPTY>"
    if normalized in _STATUS_ALLOWLIST:
        return normalized
    if upper in _CURRENCY_ALLOWLIST:
        return upper
    if pattern_token is not None:
        return pattern_token
    if _is_identifier(text):
        return "<IDENTIFIER>"
    return _number_token(text) or "<TEXT>"


class OpenAIMappingBoundary:
    def __init__(
        self,
        settings: Settings,
        *,
        client: OpenAIClient | None = None,
        limiter: InMemoryMappingLimiter | None = None,
    ) -> None:
        self._settings = settings
        self._client = client
        self._limiter = limiter or _shared_limiter(
            settings.openai_mapping_max_concurrent,
            settings.openai_mapping_requests_per_hour,
        )

    async def suggest_mapping(
        self,
        prepared: PreparedMappingPayload,
        *,
        consented_at: datetime | None,
    ) -> MappingSuggestionResult:
        requested_at = datetime.now(UTC)
        started = time.perf_counter()
        preflight_error = self._preflight_error(prepared, consented_at)
        if preflight_error is not None:
            return self._fallback(
                prepared,
                consented_at,
                requested_at,
                started,
                preflight_error,
            )

        request_id: str | None = None
        try:
            with self._limiter.acquire():
                async with asyncio.timeout(self._settings.openai_mapping_overall_timeout_seconds):
                    response = await self._get_client().responses.parse(
                        model=self._settings.openai_mapping_model,
                        input=[
                            {"role": "system", "content": _SYSTEM_PROMPT},
                            {"role": "user", "content": canonical_payload_json(prepared.payload)},
                        ],
                        store=False,
                        text_format=UniversalMappingSpec,
                    )
            request_id = getattr(response, "_request_id", None)
            parsed = response.output_parsed
            if parsed is None:
                code = (
                    MappingFallbackCode.REFUSAL
                    if _response_has_refusal(response)
                    else MappingFallbackCode.INVALID_RESPONSE
                )
                return self._fallback(
                    prepared,
                    consented_at,
                    requested_at,
                    started,
                    code,
                    request_id=request_id,
                )
            if not isinstance(parsed, UniversalMappingSpec):
                parsed = UniversalMappingSpec.model_validate(parsed)
            parsed = _date_only_mapping(parsed)
            if not _plan_uses_available_columns(parsed, prepared.payload):
                return self._fallback(
                    prepared,
                    consented_at,
                    requested_at,
                    started,
                    MappingFallbackCode.INVALID_RESPONSE,
                    request_id=request_id,
                )
        except _LimitExceededError as exc:
            code = (
                MappingFallbackCode.CONCURRENCY_LIMIT
                if exc.kind == _LimitKind.CONCURRENCY
                else MappingFallbackCode.LOCAL_RATE_LIMIT
            )
            return self._fallback(prepared, consented_at, requested_at, started, code)
        except (OpenAIError, TimeoutError, ValidationError) as exc:
            code, error_request_id = _provider_error_details(exc, request_id)
            return self._fallback(
                prepared,
                consented_at,
                requested_at,
                started,
                code,
                request_id=error_request_id,
            )

        audit = self._audit(
            prepared,
            consented_at,
            requested_at,
            started,
            outcome="suggested",
            request_id=request_id,
        )
        return MappingSuggestionSuccess(plan=parsed, audit=audit)

    def _preflight_error(
        self, prepared: PreparedMappingPayload, consented_at: datetime | None
    ) -> MappingFallbackCode | None:
        if not self._settings.openai_mapping_enabled:
            return MappingFallbackCode.DISABLED
        if self._settings.openai_api_key is None:
            return MappingFallbackCode.MISSING_API_KEY
        if consented_at is None:
            return MappingFallbackCode.CONSENT_REQUIRED
        if prepared.sha256 != payload_sha256(prepared.payload):
            return MappingFallbackCode.PAYLOAD_CHANGED
        return None

    def _get_client(self) -> OpenAIClient:
        if self._client is None:
            timeout = httpx.Timeout(
                self._settings.openai_mapping_overall_timeout_seconds,
                connect=self._settings.openai_mapping_connect_timeout_seconds,
                read=self._settings.openai_mapping_read_timeout_seconds,
            )
            self._client = AsyncOpenAI(
                api_key=self._settings.openai_api_key.get_secret_value(),
                timeout=timeout,
                max_retries=self._settings.openai_mapping_max_retries,
            )
        return self._client

    def _fallback(
        self,
        prepared: PreparedMappingPayload,
        consented_at: datetime | None,
        requested_at: datetime,
        started: float,
        code: MappingFallbackCode,
        *,
        request_id: str | None = None,
    ) -> MappingSuggestionFallback:
        error = _FALLBACK_ERRORS[code]
        audit = self._audit(
            prepared,
            consented_at,
            requested_at,
            started,
            outcome="manual_fallback",
            request_id=request_id,
            error_code=code,
        )
        return MappingSuggestionFallback(error=error, audit=audit)

    def _audit(
        self,
        prepared: PreparedMappingPayload,
        consented_at: datetime | None,
        requested_at: datetime,
        started: float,
        *,
        outcome: Literal["suggested", "manual_fallback"],
        request_id: str | None = None,
        error_code: MappingFallbackCode | None = None,
    ) -> MappingAuditMetadata:
        return MappingAuditMetadata(
            model=self._settings.openai_mapping_model,
            request_id=request_id,
            payload_sha256=prepared.sha256,
            consented_at=consented_at,
            requested_at=requested_at,
            duration_ms=max(0, round((time.perf_counter() - started) * 1000)),
            outcome=outcome,
            error_code=error_code,
        )


def _shared_limiter(max_concurrent: int, requests_per_hour: int) -> InMemoryMappingLimiter:
    key = (max_concurrent, requests_per_hour)
    with _shared_limiters_lock:
        limiter = _shared_limiters.get(key)
        if limiter is None:
            limiter = InMemoryMappingLimiter(max_concurrent, requests_per_hour)
            _shared_limiters[key] = limiter
        return limiter


def _representative_rows(
    rows: Sequence[SourceRow], columns: Sequence[InspectedColumn]
) -> list[SourceRow]:
    non_empty = [
        row for row in rows if any(not _is_empty(row.values.get(column.id)) for column in columns)
    ]
    if len(non_empty) <= MAX_SAMPLE_ROWS:
        return non_empty
    middle_start = max(4, (len(non_empty) // 2) - 2)
    indexes = [
        *range(4),
        *range(middle_start, middle_start + 4),
        *range(len(non_empty) - 4, len(non_empty)),
    ]
    return [non_empty[index] for index in dict.fromkeys(indexes)]


def _is_empty(value: Any) -> bool:
    return value is None or (isinstance(value, str) and not value.strip())


def _date_token(text: str) -> str | None:
    if _TIMESTAMP_PATTERN.fullmatch(text):
        separator = "T" if "T" in text else " "
        seconds = ":%S" if re.search(r"\d{2}:\d{2}:\d{2}", text) else ""
        fraction = ".%f" if re.search(r"\.\d+", text) else ""
        timezone = "%z" if text.endswith("Z") or re.search(r"[+-]\d{2}:?\d{2}$", text) else ""
        date_format = f"%Y-%m-%d{separator}%H:%M{seconds}{fraction}{timezone}"
        return f"<DATETIME:SAMPLE={_mask_digits(text)};FORMAT={date_format}>"
    for pattern, date_format, label in _DATE_PATTERNS:
        if not pattern.fullmatch(text):
            continue
        if label == "DD/MM/YYYY":
            first, second, _year = (int(part) for part in text.split("/"))
            if first > 12:
                possible_formats = ("%d/%m/%Y",)
            elif second > 12:
                possible_formats = ("%m/%d/%Y",)
            else:
                possible_formats = ("%d/%m/%Y", "%m/%d/%Y")
            valid_formats = tuple(
                candidate for candidate in possible_formats if _matches_date_format(text, candidate)
            )
            if valid_formats:
                format_hint = "|".join(valid_formats)
                return f"<DATE:SAMPLE={_mask_digits(text)};FORMAT={format_hint};PATTERN=DD/MM/YYYY>"
            continue
        try:
            datetime.strptime(text, date_format)
        except ValueError:
            continue
        return f"<DATE:SAMPLE={_mask_digits(text)};FORMAT={date_format};PATTERN={label}>"
    return None


def _matches_date_format(value: str, date_format: str) -> bool:
    try:
        datetime.strptime(value, date_format)
    except ValueError:
        return False
    return True


def _number_token(text: str) -> str | None:
    compact = text.strip().replace("\u00a0", " ")
    compact = re.sub(r"^[€$£¥₹]\s*|\s*[€$£¥₹]$", "", compact)
    compact = re.sub(r"^[A-Za-z]{3}\s+|\s+[A-Za-z]{3}$", "", compact)
    sample = compact
    negative_parentheses = compact.startswith("(") and compact.endswith(")")
    if negative_parentheses:
        compact = compact[1:-1].strip()
    if not _NUMBER_PATTERN.fullmatch(compact):
        return None
    if negative_parentheses or compact.startswith("-") or compact.endswith("-"):
        sign = "NEGATIVE"
    elif compact.startswith("+"):
        sign = "POSITIVE"
    else:
        sign = "NONE"
    unsigned = compact.strip("+-")
    decimal, grouping = _number_separators(unsigned)
    return (
        f"<NUMBER:SAMPLE={_mask_digits(sample)};SIGN={sign};DECIMAL={decimal};GROUPING={grouping}>"
    )


def _mask_digits(value: str) -> str:
    return re.sub(r"\d", "0", value)


def _number_separators(value: str) -> tuple[str, str]:
    punctuation = [separator for separator in (".", ",") if separator in value]
    decimal = "NONE"
    grouping = "NONE"
    if len(punctuation) == 2:
        decimal_separator = max(punctuation, key=value.rfind)
        grouping_separator = "," if decimal_separator == "." else "."
        decimal = "DOT" if decimal_separator == "." else "COMMA"
        grouping = "DOT" if grouping_separator == "." else "COMMA"
    elif punctuation:
        separator = punctuation[0]
        occurrences = value.count(separator)
        final_digits = len(value.rsplit(separator, 1)[1])
        if occurrences == 1 and final_digits in {1, 2}:
            decimal = "DOT" if separator == "." else "COMMA"
        else:
            grouping = "DOT" if separator == "." else "COMMA"
    for separator, label in (
        (" ", "SPACE"),
        ("'", "APOSTROPHE"),
        ("\u2019", "APOSTROPHE"),
    ):
        if separator in value:
            grouping = label
            break
    return decimal, grouping


def _is_identifier(text: str) -> bool:
    return bool(
        _EMAIL_PATTERN.fullmatch(text)
        or _IBAN_PATTERN.fullmatch(text)
        or _UUID_PATTERN.fullmatch(text)
        or _GROUPED_DIGITS_PATTERN.fullmatch(text)
        or _ALPHANUMERIC_ID_PATTERN.fullmatch(text)
    )


def _response_has_refusal(response: Any) -> bool:
    for item in getattr(response, "output", ()):
        for content in getattr(item, "content", ()):
            if getattr(content, "type", None) == "refusal":
                return True
    return False


def _plan_uses_available_columns(
    plan: UniversalMappingSpec, payload: MappingSuggestionPayload
) -> bool:
    available = {column.column_id for column in payload.columns}
    references = {
        value
        for key, value in _nested_items(plan.model_dump(mode="json"))
        if key in {"source_column", "debit_column", "credit_column"} and isinstance(value, str)
    }
    return references <= available


def _date_only_mapping(plan: UniversalMappingSpec) -> UniversalMappingSpec:
    timestamp = plan.transaction_timestamp
    if timestamp is None:
        return plan
    transaction_date = plan.transaction_date or DateSource(
        source_column=timestamp.source_column,
        format=timestamp.format,
    )
    return plan.model_copy(
        update={"transaction_date": transaction_date, "transaction_timestamp": None}
    )


def _nested_items(value: Any) -> Iterator[tuple[str, Any]]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield key, item
            yield from _nested_items(item)
    elif isinstance(value, list | tuple):
        for item in value:
            yield from _nested_items(item)


def _provider_error_details(
    error: OpenAIError | TimeoutError | ValidationError, request_id: str | None
) -> tuple[MappingFallbackCode, str | None]:
    if isinstance(error, AuthenticationError):
        code = MappingFallbackCode.AUTHENTICATION
    elif isinstance(error, PermissionDeniedError):
        code = MappingFallbackCode.PERMISSION
    elif isinstance(error, RateLimitError):
        code = MappingFallbackCode.PROVIDER_RATE_LIMIT
    elif isinstance(error, APITimeoutError | TimeoutError):
        code = MappingFallbackCode.TIMEOUT
    elif isinstance(error, APIConnectionError):
        code = MappingFallbackCode.CONNECTION
    elif isinstance(error, APIStatusError):
        code = MappingFallbackCode.PROVIDER_STATUS
    elif isinstance(error, ValidationError):
        code = MappingFallbackCode.INVALID_RESPONSE
    else:
        code = MappingFallbackCode.PROVIDER_ERROR
    if isinstance(error, APIStatusError):
        request_id = error.request_id
    return code, request_id


_SYSTEM_PROMPT = """You map inspected financial tables to the supplied universal import schema.
Return only a UniversalMappingSpec. Use positional column IDs exactly as supplied. Map the single
date or datetime source to transaction_date, leave transaction_timestamp null, and use an explicit
Python strptime format matching the redacted samples. Time values are discarded. For signed
amounts, EXPENSES_NEGATIVE preserves source signs and EXPENSES_POSITIVE inverts them. Never infer
personal categories or values. Use only the listed canonical fields and transformations. If the
evidence is insufficient, refuse rather than inventing a mapping."""

_FALLBACK_ERRORS = {
    MappingFallbackCode.DISABLED: MappingFallbackError(
        code=MappingFallbackCode.DISABLED,
        message="OpenAI mapping is disabled; continue with manual mapping.",
        retryable=False,
    ),
    MappingFallbackCode.MISSING_API_KEY: MappingFallbackError(
        code=MappingFallbackCode.MISSING_API_KEY,
        message="OpenAI mapping is not configured; continue with manual mapping.",
        retryable=False,
    ),
    MappingFallbackCode.CONSENT_REQUIRED: MappingFallbackError(
        code=MappingFallbackCode.CONSENT_REQUIRED,
        message="Explicit consent is required; continue with manual mapping.",
        retryable=False,
    ),
    MappingFallbackCode.PAYLOAD_CHANGED: MappingFallbackError(
        code=MappingFallbackCode.PAYLOAD_CHANGED,
        message="The reviewed mapping payload changed; review it again or map manually.",
        retryable=False,
    ),
    MappingFallbackCode.CONCURRENCY_LIMIT: MappingFallbackError(
        code=MappingFallbackCode.CONCURRENCY_LIMIT,
        message="Another mapping suggestion is running; retry later or map manually.",
        retryable=True,
    ),
    MappingFallbackCode.LOCAL_RATE_LIMIT: MappingFallbackError(
        code=MappingFallbackCode.LOCAL_RATE_LIMIT,
        message="The local mapping suggestion limit was reached; retry later or map manually.",
        retryable=True,
    ),
    MappingFallbackCode.AUTHENTICATION: MappingFallbackError(
        code=MappingFallbackCode.AUTHENTICATION,
        message="The mapping provider rejected its credentials; continue with manual mapping.",
        retryable=False,
    ),
    MappingFallbackCode.PERMISSION: MappingFallbackError(
        code=MappingFallbackCode.PERMISSION,
        message="The mapping provider denied access; continue with manual mapping.",
        retryable=False,
    ),
    MappingFallbackCode.CONNECTION: MappingFallbackError(
        code=MappingFallbackCode.CONNECTION,
        message="The mapping provider is unreachable; retry later or map manually.",
        retryable=True,
    ),
    MappingFallbackCode.TIMEOUT: MappingFallbackError(
        code=MappingFallbackCode.TIMEOUT,
        message="The mapping suggestion timed out; retry later or map manually.",
        retryable=True,
    ),
    MappingFallbackCode.PROVIDER_RATE_LIMIT: MappingFallbackError(
        code=MappingFallbackCode.PROVIDER_RATE_LIMIT,
        message="The mapping provider rate limit was reached; retry later or map manually.",
        retryable=True,
    ),
    MappingFallbackCode.PROVIDER_STATUS: MappingFallbackError(
        code=MappingFallbackCode.PROVIDER_STATUS,
        message="The mapping provider returned an error; continue with manual mapping.",
        retryable=True,
    ),
    MappingFallbackCode.REFUSAL: MappingFallbackError(
        code=MappingFallbackCode.REFUSAL,
        message="The mapping provider declined the request; continue with manual mapping.",
        retryable=False,
    ),
    MappingFallbackCode.INVALID_RESPONSE: MappingFallbackError(
        code=MappingFallbackCode.INVALID_RESPONSE,
        message="The mapping suggestion was invalid; continue with manual mapping.",
        retryable=False,
    ),
    MappingFallbackCode.PROVIDER_ERROR: MappingFallbackError(
        code=MappingFallbackCode.PROVIDER_ERROR,
        message="The mapping provider failed; continue with manual mapping.",
        retryable=True,
    ),
}
