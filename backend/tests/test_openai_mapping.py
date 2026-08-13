import asyncio
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from openai import AuthenticationError
from openai.lib._pydantic import to_strict_json_schema
from pydantic import SecretStr

from backend.app.config import Settings
from backend.app.imports.models import (
    ConstantCurrency,
    DateSource,
    ImportFileType,
    ImportInspection,
    InferredValueType,
    InspectedColumn,
    NumberFormat,
    SheetInspection,
    SignedAmount,
    SourceRow,
    TextSource,
    UniversalMappingSpec,
)
from backend.app.imports.openai_mapping import (
    InMemoryMappingLimiter,
    MappingFallbackCode,
    MappingSuggestionFallback,
    MappingSuggestionSuccess,
    OpenAIMappingBoundary,
    PreparedMappingPayload,
    canonical_payload_json,
    prepare_mapping_payload,
    redact_cell,
)


class FakeResponses:
    def __init__(self, response=None, error: Exception | None = None) -> None:
        self.response = response
        self.error = error
        self.calls: list[dict] = []
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.block = False

    async def parse(self, **kwargs):
        self.calls.append(kwargs)
        self.started.set()
        if self.block:
            await self.release.wait()
        if self.error is not None:
            raise self.error
        return self.response


class FakeClient:
    def __init__(self, responses: FakeResponses) -> None:
        self.responses = responses


def _columns() -> tuple[InspectedColumn, ...]:
    return (
        InspectedColumn(
            id="c000",
            position=0,
            raw_label="Booked at",
            normalized_label="booked at",
            inferred_type=InferredValueType.DATE,
        ),
        InspectedColumn(
            id="c001",
            position=1,
            raw_label="Merchant Alice Household 1234",
            normalized_label="merchant alice household 1234",
            inferred_type=InferredValueType.TEXT,
        ),
        InspectedColumn(
            id="c002",
            position=2,
            raw_label="Amount",
            normalized_label="amount",
            inferred_type=InferredValueType.NUMBER,
        ),
        InspectedColumn(
            id="c003",
            position=3,
            raw_label="Currency",
            normalized_label="currency",
            inferred_type=InferredValueType.CURRENCY,
        ),
        InspectedColumn(
            id="c004",
            position=4,
            raw_label="Status",
            normalized_label="status",
            inferred_type=InferredValueType.TEXT,
        ),
        InspectedColumn(
            id="c005",
            position=5,
            raw_label="Reference",
            normalized_label="reference",
            inferred_type=InferredValueType.TEXT,
        ),
    )


def _prepared(row_count: int = 1) -> PreparedMappingPayload:
    rows = tuple(
        SourceRow(
            row_number=index + 2,
            values={
                "c000": f"2026-08-{index + 1:02d}",
                "c001": f"Private merchant {index}",
                "c002": f"-{index + 1},25",
                "c003": "eur",
                "c004": "Completed",
                "c005": f"TXN-{100000 + index}",
            },
        )
        for index in range(row_count)
    )
    inspection = ImportInspection(
        file_type=ImportFileType.CSV,
        encoding="utf-8",
        delimiter=",",
        quote_character='"',
        sheets=(SheetInspection(name="CSV", index=0, row_count=row_count + 1, column_count=6),),
        selected_sheet="CSV",
        header_row=1,
        data_start_row=2,
        data_end_row=row_count + 1,
        row_count=row_count,
        columns=_columns(),
        preview=rows,
        structural_signature="a" * 64,
    )
    return prepare_mapping_payload(inspection)


def _plan() -> UniversalMappingSpec:
    return UniversalMappingSpec(
        transaction_date=DateSource(source_column="c000", format="%Y-%m-%d"),
        description=TextSource(source_column="c001"),
        amount=SignedAmount(
            source_column="c002",
            number_format=NumberFormat(decimal_separator=","),
        ),
        currency=ConstantCurrency(value="EUR"),
    )


def _settings(tmp_path: Path, **overrides) -> Settings:
    values = {
        "data_dir": tmp_path,
        "openai_mapping_enabled": True,
        "openai_api_key": SecretStr("sk-test-secret"),
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


def test_redaction_allowlists_patterns_and_sensitive_text() -> None:
    assert redact_cell("eur") == "EUR"
    assert redact_cell("Completed") == "completed"
    assert redact_cell("2026-08-12") == (
        "<DATE:SAMPLE=0000-00-00;FORMAT=%Y-%m-%d;PATTERN=YYYY-MM-DD>"
    )
    assert redact_cell("12.08.2026") == (
        "<DATE:SAMPLE=00.00.0000;FORMAT=%d.%m.%Y;PATTERN=DD.MM.YYYY>"
    )
    assert redact_cell("08/09/2026") == (
        "<DATE:SAMPLE=00/00/0000;FORMAT=%d/%m/%Y|%m/%d/%Y;PATTERN=DD/MM/YYYY>"
    )
    assert redact_cell("08/13/2026") == (
        "<DATE:SAMPLE=00/00/0000;FORMAT=%m/%d/%Y;PATTERN=DD/MM/YYYY>"
    )
    assert redact_cell("2026-08-12T12:30:00+02:00") == (
        "<DATETIME:SAMPLE=0000-00-00T00:00:00+00:00;FORMAT=%Y-%m-%dT%H:%M:%S%z>"
    )
    assert redact_cell("-1.234,56 EUR") == (
        "<NUMBER:SAMPLE=-0.000,00;SIGN=NEGATIVE;DECIMAL=COMMA;GROUPING=DOT>"
    )
    assert redact_cell("(1,234.56)") == (
        "<NUMBER:SAMPLE=(0,000.00);SIGN=NEGATIVE;DECIMAL=DOT;GROUPING=COMMA>"
    )
    assert redact_cell("SI56 1910 0001 2345 678") == "<IDENTIFIER>"
    assert redact_cell("4111111111111111") == "<IDENTIFIER>"
    assert redact_cell("person@example.com") == "<IDENTIFIER>"
    assert redact_cell("Private Merchant Name") == "<TEXT>"
    assert redact_cell("Groceries") == "<TEXT>"


def test_payload_sampling_is_representative_deterministic_and_canonical() -> None:
    first = _prepared(row_count=20)
    second = _prepared(row_count=20)

    assert len(first.payload.representative_rows) == 12
    assert first.payload.representative_rows == second.payload.representative_rows
    assert first.sha256 == second.sha256
    assert first.payload.representative_rows[0][1] == "<TEXT>"
    assert first.payload.representative_rows[4][0].startswith("<DATE:SAMPLE=0000-00-")
    assert first.payload.representative_rows[-1][5] == "<IDENTIFIER>"
    assert "Private merchant" not in canonical_payload_json(first.payload)
    assert len(first.sha256) == 64


def test_payload_redacts_user_controlled_headers_but_keeps_semantics_and_positions() -> None:
    prepared = _prepared()

    assert [column.column_id for column in prepared.payload.columns] == [
        "c000",
        "c001",
        "c002",
        "c003",
        "c004",
        "c005",
    ]
    assert [column.header for column in prepared.payload.columns] == [
        "timestamp",
        "description",
        "amount",
        "currency",
        "status",
        "reference",
    ]
    serialized = canonical_payload_json(prepared.payload)
    assert "Booked at" not in serialized
    assert "Alice Household 1234" not in serialized


def test_structured_output_schema_avoids_unsupported_keywords() -> None:
    schema = json.dumps(to_strict_json_schema(UniversalMappingSpec))

    assert "uniqueItems" not in schema
    assert '"oneOf"' not in schema


def test_payload_redacts_numeric_identifier_columns() -> None:
    assert redact_cell("12345", column=_columns()[5]) == "<IDENTIFIER>"


@pytest.mark.anyio
async def test_disabled_mapping_returns_manual_fallback_without_calling_provider(
    tmp_path: Path,
) -> None:
    responses = FakeResponses()
    settings = Settings(data_dir=tmp_path)
    result = await OpenAIMappingBoundary(settings, client=FakeClient(responses)).suggest_mapping(
        _prepared(), consented_at=datetime.now(UTC)
    )

    assert isinstance(result, MappingSuggestionFallback)
    assert result.error.code == MappingFallbackCode.DISABLED
    assert result.audit.outcome == "manual_fallback"
    assert responses.calls == []


@pytest.mark.anyio
async def test_structured_response_returns_plan_and_safe_audit_metadata(tmp_path: Path) -> None:
    parsed = _plan()
    responses = FakeResponses(
        SimpleNamespace(output_parsed=parsed, _request_id="req_safe", output=[])
    )
    consented_at = datetime.now(UTC)

    result = await OpenAIMappingBoundary(
        _settings(tmp_path), client=FakeClient(responses)
    ).suggest_mapping(_prepared(), consented_at=consented_at)

    assert isinstance(result, MappingSuggestionSuccess)
    assert result.plan == parsed
    assert result.audit.request_id == "req_safe"
    assert result.audit.consented_at == consented_at
    assert responses.calls[0]["model"] == "gpt-4.1-mini"
    assert responses.calls[0]["store"] is False
    assert responses.calls[0]["text_format"] is UniversalMappingSpec
    dumped_result = result.model_dump_json()
    assert "sk-test-secret" not in dumped_result
    assert "Private merchant" not in dumped_result
    assert not hasattr(result.audit, "payload")
    assert not hasattr(result.audit, "raw_response")


@pytest.mark.anyio
async def test_provider_error_is_sanitized_for_manual_fallback(tmp_path: Path) -> None:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    provider_response = httpx.Response(
        401,
        request=request,
        json={"error": {"message": "sensitive provider body"}},
        headers={"x-request-id": "req_failed"},
    )
    responses = FakeResponses(
        error=AuthenticationError(
            "provider leaked detail", response=provider_response, body=provider_response.json()
        )
    )

    result = await OpenAIMappingBoundary(
        _settings(tmp_path), client=FakeClient(responses)
    ).suggest_mapping(_prepared(), consented_at=datetime.now(UTC))

    assert isinstance(result, MappingSuggestionFallback)
    assert result.error.code == MappingFallbackCode.AUTHENTICATION
    assert result.audit.request_id == "req_failed"
    serialized = result.model_dump_json()
    assert "sensitive provider body" not in serialized
    assert "provider leaked detail" not in serialized
    assert "sk-test-secret" not in serialized


@pytest.mark.anyio
async def test_unknown_plan_column_returns_manual_fallback(tmp_path: Path) -> None:
    invalid_plan = _plan().model_copy(update={"description": TextSource(source_column="c999")})
    responses = FakeResponses(
        SimpleNamespace(output_parsed=invalid_plan, _request_id="req_invalid", output=[])
    )

    result = await OpenAIMappingBoundary(
        _settings(tmp_path), client=FakeClient(responses)
    ).suggest_mapping(_prepared(), consented_at=datetime.now(UTC))

    assert isinstance(result, MappingSuggestionFallback)
    assert result.error.code == MappingFallbackCode.INVALID_RESPONSE
    assert result.audit.request_id == "req_invalid"


@pytest.mark.anyio
async def test_limiter_rejects_concurrent_request_and_tenth_hourly_overflow(
    tmp_path: Path,
) -> None:
    responses = FakeResponses(
        SimpleNamespace(
            output_parsed=_plan(),
            _request_id="req_safe",
            output=[],
        )
    )
    responses.block = True
    limiter = InMemoryMappingLimiter(max_concurrent=1, requests_per_hour=10)
    boundary = OpenAIMappingBoundary(
        _settings(tmp_path), client=FakeClient(responses), limiter=limiter
    )
    consented_at = datetime.now(UTC)

    active = asyncio.create_task(boundary.suggest_mapping(_prepared(), consented_at=consented_at))
    await responses.started.wait()
    concurrent = await boundary.suggest_mapping(_prepared(), consented_at=consented_at)
    responses.release.set()
    await active

    assert isinstance(concurrent, MappingSuggestionFallback)
    assert concurrent.error.code == MappingFallbackCode.CONCURRENCY_LIMIT

    responses.block = False
    for _ in range(9):
        assert isinstance(
            await boundary.suggest_mapping(_prepared(), consented_at=consented_at),
            MappingSuggestionSuccess,
        )
    limited = await boundary.suggest_mapping(_prepared(), consented_at=consented_at)
    assert isinstance(limited, MappingSuggestionFallback)
    assert limited.error.code == MappingFallbackCode.LOCAL_RATE_LIMIT


def test_openai_key_is_secret_and_limits_default_disabled(tmp_path: Path) -> None:
    settings = Settings(
        data_dir=tmp_path,
        openai_api_key="sk-never-print",
        allowed_hosts_setting="finance.test, finance.internal",
        allowed_origins_setting="https://finance.test",
    )

    assert settings.openai_mapping_enabled is False
    assert isinstance(settings.openai_api_key, SecretStr)
    assert "sk-never-print" not in repr(settings)
    assert settings.openai_mapping_max_concurrent == 1
    assert settings.openai_mapping_requests_per_hour == 10
    assert settings.allowed_hosts == ("finance.test", "finance.internal")
    assert settings.allowed_origins == ("https://finance.test",)
    assert (
        Settings(
            data_dir=tmp_path,
            openai_api_key="   ",
        ).openai_api_key
        is None
    )
