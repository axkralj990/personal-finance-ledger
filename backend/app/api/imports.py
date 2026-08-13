import hashlib
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Annotated, Any
from urllib.parse import urlsplit

from fastapi import APIRouter, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.api.dependencies import SessionDependency
from backend.app.api.pagination import Page
from backend.app.database.models import (
    Account,
    BatchStatus,
    DuplicateStatus,
    ImportBatch,
    ImportBatchExecutionPlan,
    ImportMappingTemplateOrigin,
    StagedDisposition,
    StagedTransaction,
    Transaction,
    TransactionKind,
)
from backend.app.imports.lifecycle import ImportMappingTemplateService, UniversalImportService
from backend.app.imports.models import UniversalMappingSpec
from backend.app.imports.openai_mapping import OpenAIMappingBoundary
from backend.app.imports.schemas import (
    InspectionPatch,
    InspectionRead,
    LifecycleRequest,
    MappingConfirmRead,
    MappingConfirmRequest,
    MappingPreviewRead,
    MappingPreviewRequest,
    StageRequest,
    SuggestionPayloadRead,
    SuggestionRead,
    SuggestionRequest,
    TemplateCreate,
    TemplatePatch,
    TemplateRead,
)
from backend.app.imports.service import ImportService
from backend.app.problems import Problem

router = APIRouter(tags=["imports"])


class BatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    original_filename: str
    file_sha256: str
    parser_version: str
    status: BatchStatus
    revision: int
    mapping_revision: int
    inspection_version: str | None
    structural_signature: str | None
    current_mapping_origin: ImportMappingTemplateOrigin | None
    source_mapping_template_id: str | None
    source_mapping_template_version_id: str | None
    current_mapping_diagnostics: list[dict[str, Any]] = Field(default_factory=list)
    current_execution_plan: UniversalMappingSpec | None = None
    total_rows: int
    valid_rows: int = 0
    needs_review_rows: int = 0
    duplicate_rows: int = 0
    included_rows: int
    ignored_rows: int
    audit_rows: int = 0
    blocked_rows: int = 0
    errors: list[str] = Field(default_factory=list)
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    committed_at: datetime | None


class DuplicateCandidateRead(BaseModel):
    id: str
    transaction_date: date
    description: str
    amount_minor: int
    currency: str
    account_name: str


class StagedRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    account_id: str
    row_number: int
    raw_json: dict[str, Any]
    transaction_date: date | None
    transaction_at: datetime | None
    description: str | None
    amount_minor: int | None
    currency: str | None
    kind: TransactionKind | None
    category_id: str | None
    subcategory_id: str | None
    predicted_category_id: str | None
    predicted_subcategory_id: str | None
    prediction_confidence: float | None
    validation_issues: list[dict[str, Any]]
    duplicate_status: DuplicateStatus
    duplicate_candidate_id: str | None
    duplicate_candidate: DuplicateCandidateRead | None = None
    duplicate_explanation: str | None
    disposition: StagedDisposition
    ignore_reason: str | None
    remember_correction: bool
    revision: int


class StagedRowPatch(BaseModel):
    id: str
    expected_revision: int = Field(ge=1)
    transaction_date: date | None = None
    description: str | None = None
    amount_minor: int | None = None
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category_id: str | None = None
    subcategory_id: str | None = None
    disposition: StagedDisposition | None = None
    ignore_reason: str | None = None
    remember_correction: bool | None = None

    @field_validator("amount_minor")
    @classmethod
    def nonzero_amount(cls, value: int | None) -> int | None:
        if value == 0:
            raise ValueError("amount must not be zero")
        return value


class BulkStagedPatch(BaseModel):
    rows: list[StagedRowPatch] = Field(min_length=1)
    expected_revision: int = Field(ge=1)


class ManualRow(BaseModel):
    transaction_date: date
    description: str = Field(min_length=1)
    amount_minor: int
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category_id: str | None = None
    subcategory_id: str | None = None

    @field_validator("amount_minor")
    @classmethod
    def nonzero_amount(cls, value: int) -> int:
        if value == 0:
            raise ValueError("amount must not be zero")
        return value


class ManualImportCreate(BaseModel):
    account_id: str
    rows: list[ManualRow] = Field(min_length=1)


@router.post("/imports", response_model=BatchRead, status_code=201)
async def create_import(
    request: Request,
    session: SessionDependency,
    account_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
    response: Response,
    expected_revision: Annotated[int | None, Form(ge=1)] = None,
) -> BatchRead:
    account = session.get(Account, account_id)
    if account is None or not account.is_active:
        raise Problem(404, "account_not_found", "Active account was not found")
    uploads = request.app.state.settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    retained_path = uploads / str(uuid.uuid4())
    digest = hashlib.sha256()
    total = 0
    try:
        try:
            with retained_path.open("wb") as target:
                while chunk := await file.read(1024 * 1024):
                    total += len(chunk)
                    if total > request.app.state.settings.max_upload_bytes:
                        return _raise_file_too_large()
                    digest.update(chunk)
                    target.write(chunk)
        except BaseException:
            retained_path.unlink(missing_ok=True)
            raise
    finally:
        await file.close()
    service = UniversalImportService(
        request.app.state.settings.max_file_rows, request.app.state.settings.data_dir
    )
    try:
        batch, created = service.create_upload(
            session, account, retained_path, file.filename or "upload", digest.hexdigest()
        )
        if not created:
            retained_path.unlink(missing_ok=True)
            if expected_revision is not None:
                _check_batch_revision(batch, expected_revision)
            response.status_code = 200
            response.headers["X-Existing-Import-Draft"] = "true"
        return _batch_reads(session, [batch])[0]
    except Problem as exc:
        if exc.body.code.startswith("duplicate_file"):
            retained_path.unlink(missing_ok=True)
        raise


@router.get("/imports", response_model=Page[BatchRead])
def list_imports(
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[BatchRead]:
    condition = ImportBatch.status != BatchStatus.DELETED
    total = int(session.scalar(select(func.count()).select_from(ImportBatch).where(condition)) or 0)
    items = list(
        session.scalars(
            select(ImportBatch)
            .where(condition)
            .order_by(ImportBatch.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(items=_batch_reads(session, items), page=page, page_size=page_size, total=total)


@router.get("/imports/{batch_id}", response_model=BatchRead)
def get_import(batch_id: str, session: SessionDependency) -> BatchRead:
    return _batch_reads(session, [_batch(session, batch_id)])[0]


@router.get("/imports/{batch_id}/source-file", response_class=FileResponse)
def download_import_source(batch_id: str, session: SessionDependency) -> FileResponse:
    batch = _batch(session, batch_id)
    if not batch.retained_path or not (path := Path(batch.retained_path)).is_file():
        raise Problem(410, "source_file_missing", "Retained source file is missing")
    return FileResponse(
        path,
        filename=batch.original_filename,
        media_type="application/octet-stream",
    )


@router.get("/imports/{batch_id}/inspection", response_model=InspectionRead)
def get_import_inspection(
    batch_id: str,
    request: Request,
    session: SessionDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> InspectionRead:
    batch = _batch(session, batch_id)
    service = _universal_service(request)
    inspection = service.inspection(session, batch, offset, limit)
    return InspectionRead(
        batch_id=batch.id,
        revision=batch.revision,
        inspection=inspection,
        proposals=service.proposals(session, batch, inspection),
    )


@router.patch("/imports/{batch_id}/inspection", response_model=InspectionRead)
def patch_import_inspection(
    batch_id: str,
    payload: InspectionPatch,
    request: Request,
    session: SessionDependency,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 100,
) -> InspectionRead:
    batch = _batch(session, batch_id)
    service = _universal_service(request)
    inspection = service.update_inspection(
        session,
        batch,
        payload.expected_revision,
        payload.selected_sheet,
        payload.header_row,
        offset,
        limit,
        payload.confirm_restaging,
    )
    return InspectionRead(
        batch_id=batch.id,
        revision=batch.revision,
        inspection=inspection,
        proposals=service.proposals(session, batch, inspection),
    )


@router.post("/imports/{batch_id}/mapping-preview", response_model=MappingPreviewRead)
def preview_import_mapping(
    batch_id: str,
    payload: MappingPreviewRequest,
    request: Request,
    session: SessionDependency,
) -> MappingPreviewRead:
    batch = _draft_batch(session, batch_id)
    return _universal_service(request).preview(
        batch, payload.execution_plan, payload.offset, payload.limit
    )


@router.put("/imports/{batch_id}/mapping", response_model=MappingConfirmRead)
def confirm_import_mapping(
    batch_id: str,
    payload: MappingConfirmRequest,
    request: Request,
    session: SessionDependency,
) -> MappingConfirmRead:
    batch = _batch(session, batch_id)
    snapshot = _universal_service(request).confirm_mapping(
        session,
        batch,
        payload.expected_revision,
        payload.execution_plan,
        payload.source_template_id,
        payload.source_template_version_id,
        payload.confirm_restaging,
    )
    return MappingConfirmRead(
        batch_id=batch.id,
        revision=batch.revision,
        mapping_revision=batch.mapping_revision,
        execution_plan=UniversalMappingSpec.model_validate(snapshot.plan_json),
    )


@router.post("/imports/{batch_id}/stage", response_model=BatchRead)
def stage_import(
    batch_id: str,
    payload: StageRequest,
    request: Request,
    session: SessionDependency,
) -> BatchRead:
    batch = _universal_service(request).stage(
        session,
        _batch(session, batch_id),
        payload.expected_revision,
        payload.expected_mapping_revision,
    )
    return _batch_reads(session, [batch])[0]


@router.get("/imports/{batch_id}/mapping-suggestion-payload", response_model=SuggestionPayloadRead)
def get_mapping_suggestion_payload(
    batch_id: str, request: Request, session: SessionDependency
) -> SuggestionPayloadRead:
    _require_mapping_request(request)
    batch = _draft_batch(session, batch_id)
    prepared = _universal_service(request).suggestion_payload(batch)
    return SuggestionPayloadRead(
        batch_id=batch.id,
        revision=batch.revision,
        sha256=prepared.sha256,
        payload=prepared.payload,
    )


@router.post("/imports/{batch_id}/mapping-suggestion", response_model=SuggestionRead)
async def suggest_import_mapping(
    batch_id: str,
    payload: SuggestionRequest,
    request: Request,
    session: SessionDependency,
) -> SuggestionRead:
    _require_mapping_request(request, require_json=True, require_origin=True)
    batch = _draft_batch(session, batch_id)
    if batch.revision != payload.expected_revision:
        _raise_batch_revision(batch)
    service = _universal_service(request)
    prepared = service.suggestion_payload(batch)
    if prepared.sha256 != payload.payload_sha256:
        raise Problem(
            409,
            "mapping_payload_changed",
            "The mapping payload changed; review it again",
            recoverable=True,
            details={"current_revision": batch.revision, "sha256": prepared.sha256},
        )
    session.rollback()

    boundary_factory = request.app.state.openai_mapping_boundary_factory
    boundary: OpenAIMappingBoundary = boundary_factory(request.app.state.settings)
    result = await boundary.suggest_mapping(prepared, consented_at=datetime.now(UTC))
    if result.status == "suggested":
        result = service.validate_suggestion(batch, result)

    async with request.app.state.sqlite_write_lock:
        with request.app.state.database.session() as persistence_session:
            current, stale = service.record_suggestion(
                persistence_session, batch_id, payload.expected_revision, result
            )
            if stale:
                _raise_batch_revision(current)
            return SuggestionRead(batch_id=batch_id, revision=current.revision, result=result)


@router.get("/import-mappings", response_model=list[TemplateRead])
def list_import_mappings(
    session: SessionDependency,
    account_id: str | None = None,
    structural_signature: Annotated[str | None, Query(pattern=r"^[0-9a-f]{64}$")] = None,
    include_inactive: bool = False,
) -> list[TemplateRead]:
    return ImportMappingTemplateService().list(
        session,
        account_id=account_id,
        structural_signature=structural_signature,
        include_inactive=include_inactive,
    )


@router.post("/import-mappings", response_model=TemplateRead, status_code=201)
def create_import_mapping(payload: TemplateCreate, session: SessionDependency) -> TemplateRead:
    service = ImportMappingTemplateService()
    template = service.create(
        session,
        name=payload.name,
        structural_signature=payload.structural_signature,
        account_id=payload.account_id,
        plan=payload.execution_plan,
        source_batch_id=payload.source_batch_id,
        source_batch_revision=payload.source_batch_revision,
    )
    return service.read(service.get(session, template.id), include_versions=True)


@router.get("/import-mappings/{template_id}", response_model=TemplateRead)
def get_import_mapping(template_id: str, session: SessionDependency) -> TemplateRead:
    service = ImportMappingTemplateService()
    return service.read(service.get(session, template_id), include_versions=True)


@router.patch("/import-mappings/{template_id}", response_model=TemplateRead)
def patch_import_mapping(
    template_id: str, payload: TemplatePatch, session: SessionDependency
) -> TemplateRead:
    service = ImportMappingTemplateService()
    template = service.patch(
        session,
        service.get(session, template_id),
        expected_revision=payload.expected_revision,
        name=payload.name,
        is_active=payload.is_active,
        plan=payload.execution_plan,
    )
    return service.read(service.get(session, template.id), include_versions=True)


@router.get("/imports/{batch_id}/rows", response_model=Page[StagedRowRead])
def list_import_rows(
    batch_id: str,
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=500)] = 100,
) -> Page[StagedRowRead]:
    _batch(session, batch_id)
    condition = StagedTransaction.batch_id == batch_id
    total = int(
        session.scalar(select(func.count()).select_from(StagedTransaction).where(condition)) or 0
    )
    items = list(
        session.scalars(
            select(StagedTransaction)
            .where(condition)
            .order_by(StagedTransaction.row_number)
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(
        items=_staged_row_reads(session, items), page=page, page_size=page_size, total=total
    )


@router.patch("/imports/{batch_id}/rows", response_model=list[StagedRowRead])
def patch_import_rows(
    batch_id: str, payload: BulkStagedPatch, request: Request, session: SessionDependency
) -> list[StagedRowRead]:
    batch = _draft_batch(session, batch_id)
    changes = [row.model_dump(exclude_unset=True) for row in payload.rows]
    updated = ImportService(
        request.app.state.settings.max_file_rows, request.app.state.settings.data_dir
    ).update_rows(session, batch, payload.expected_revision, changes)
    return _staged_row_reads(session, updated)


@router.post("/imports/{batch_id}/commit", response_model=BatchRead)
def commit_import(
    batch_id: str,
    request: Request,
    session: SessionDependency,
    payload: LifecycleRequest,
) -> BatchRead:
    batch = _batch(session, batch_id)
    ImportService(
        request.app.state.settings.max_file_rows, request.app.state.settings.data_dir
    ).commit(session, batch, expected_revision=payload.expected_revision)
    return _batch_reads(session, [batch])[0]


@router.delete("/imports/{batch_id}", status_code=204)
def delete_import(batch_id: str, payload: LifecycleRequest, session: SessionDependency) -> None:
    batch = _draft_batch(session, batch_id)
    _check_batch_revision(batch, payload.expected_revision)
    if batch.status in {BatchStatus.FAILED, BatchStatus.DELETED}:
        raise Problem(409, "terminal_import", "Terminal imports cannot be changed")
    batch.status = BatchStatus.DELETED
    batch.revision += 1
    batch.updated_at = datetime.now(UTC)
    session.commit()


@router.post("/manual-imports", response_model=BatchRead, status_code=201)
def create_manual_import(
    payload: ManualImportCreate, request: Request, session: SessionDependency
) -> BatchRead:
    account = session.get(Account, payload.account_id)
    if account is None or not account.is_active:
        raise Problem(404, "account_not_found", "Active account was not found")
    rows = [row.model_dump(mode="json") for row in payload.rows]
    batch = ImportService(
        request.app.state.settings.max_file_rows, request.app.state.settings.data_dir
    ).stage_manual(session, account, rows)
    return _batch_reads(session, [batch])[0]


def _batch(session: Session, batch_id: str) -> ImportBatch:
    batch = session.get(ImportBatch, batch_id)
    if batch is None or batch.status == BatchStatus.DELETED:
        raise Problem(404, "import_not_found", "Import batch was not found")
    return batch


def _draft_batch(session: Session, batch_id: str) -> ImportBatch:
    batch = _batch(session, batch_id)
    if batch.status in {BatchStatus.COMMITTED, BatchStatus.FAILED}:
        raise Problem(409, "terminal_import", "Terminal imports cannot be changed")
    return batch


def _raise_file_too_large() -> Any:
    raise Problem(413, "file_too_large", "Upload exceeds the configured size limit")


def _universal_service(request: Request) -> UniversalImportService:
    settings = request.app.state.settings
    return UniversalImportService(settings.max_file_rows, settings.data_dir)


def _check_batch_revision(batch: ImportBatch, expected_revision: int) -> None:
    if batch.revision != expected_revision:
        _raise_batch_revision(batch)


def _raise_batch_revision(batch: ImportBatch) -> Any:
    raise Problem(
        409,
        "revision_conflict",
        "The import changed since it was loaded",
        recoverable=True,
        details={"current_revision": batch.revision},
    )


def _require_mapping_request(
    request: Request, *, require_json: bool = False, require_origin: bool = False
) -> None:
    if require_json:
        content_type = request.headers.get("content-type", "").partition(";")[0].strip().casefold()
        if content_type != "application/json":
            raise Problem(415, "json_required", "Mapping suggestions require application/json")
    settings = request.app.state.settings
    request_authority = request.headers.get("host", "").casefold()
    request_host = _hostname(request_authority)
    allowed_hosts = {host.casefold() for host in settings.allowed_hosts}
    if request_authority not in allowed_hosts and request_host not in allowed_hosts:
        raise Problem(403, "host_not_allowed", "Mapping requests require an allowed Host")
    if request.headers.get("sec-fetch-site", "").casefold() == "cross-site":
        raise Problem(403, "same_origin_required", "Cross-site mapping requests are not allowed")
    origin = request.headers.get("origin")
    if origin is None:
        if require_origin:
            raise Problem(403, "same_origin_required", "Mapping suggestions require Origin")
        return
    parsed = urlsplit(origin)
    canonical_origin = f"{parsed.scheme.casefold()}://{parsed.netloc.casefold()}"
    allowed_origins = {item.casefold().rstrip("/") for item in settings.allowed_origins}
    valid_origin = (
        canonical_origin in allowed_origins and parsed.netloc.casefold() == request_authority
    )
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or not valid_origin
    ):
        raise Problem(
            403,
            "same_origin_required",
            "Mapping suggestions require a same-origin request",
        )


def _hostname(authority: str) -> str:
    return (urlsplit(f"//{authority}").hostname or "").casefold()


def _batch_reads(session: Session, batches: list[ImportBatch]) -> list[BatchRead]:
    if not batches:
        return []
    batch_ids = [batch.id for batch in batches]
    aggregate_rows = session.execute(
        select(
            StagedTransaction.batch_id,
            func.sum(
                case(
                    (
                        StagedTransaction.disposition.in_(
                            [StagedDisposition.INCLUDE, StagedDisposition.COMMITTED]
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        StagedTransaction.disposition.in_(
                            [StagedDisposition.PENDING, StagedDisposition.BLOCKED]
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (StagedTransaction.duplicate_status != DuplicateStatus.NONE, 1),
                    else_=0,
                )
            ),
            func.sum(
                case(
                    (
                        StagedTransaction.disposition.in_(
                            [
                                StagedDisposition.IGNORE,
                                StagedDisposition.BLOCKED,
                                StagedDisposition.AUDIT_ONLY,
                            ]
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            func.sum(
                case((StagedTransaction.disposition == StagedDisposition.AUDIT_ONLY, 1), else_=0)
            ),
            func.sum(
                case((StagedTransaction.disposition == StagedDisposition.BLOCKED, 1), else_=0)
            ),
        )
        .where(StagedTransaction.batch_id.in_(batch_ids))
        .group_by(StagedTransaction.batch_id)
    )
    counts = {
        batch_id: tuple(int(value or 0) for value in values) for batch_id, *values in aggregate_rows
    }
    snapshots: dict[str, UniversalMappingSpec] = {}
    for snapshot in session.scalars(
        select(ImportBatchExecutionPlan)
        .where(ImportBatchExecutionPlan.batch_id.in_(batch_ids))
        .order_by(ImportBatchExecutionPlan.mapping_revision)
    ):
        try:
            snapshots[snapshot.batch_id] = UniversalMappingSpec.model_validate(snapshot.plan_json)
        except ValidationError:
            # Historical adapter snapshots stay persisted for audit but are not active plans.
            continue
    for batch in batches:
        if batch.current_mapping_origin is None:
            snapshots.pop(batch.id, None)
    return [
        BatchRead.model_validate(batch).model_copy(
            update={
                "valid_rows": counts.get(batch.id, (0, 0, 0))[0],
                "needs_review_rows": counts.get(batch.id, (0, 0, 0))[1],
                "duplicate_rows": counts.get(batch.id, (0, 0, 0))[2],
                "included_rows": counts.get(batch.id, (0, 0, 0))[0],
                "ignored_rows": counts.get(batch.id, (0, 0, 0, 0, 0, 0))[3],
                "audit_rows": counts.get(batch.id, (0, 0, 0, 0, 0, 0))[4],
                "blocked_rows": counts.get(batch.id, (0, 0, 0, 0, 0, 0))[5],
                "current_execution_plan": snapshots.get(batch.id),
                "errors": [batch.error_message] if batch.error_message else [],
            }
        )
        for batch in batches
    ]


def _staged_row_reads(session: Session, rows: list[StagedTransaction]) -> list[StagedRowRead]:
    candidate_ids = {row.duplicate_candidate_id for row in rows if row.duplicate_candidate_id}
    candidates = {
        candidate.id: candidate
        for candidate in session.scalars(
            select(Transaction)
            .options(joinedload(Transaction.account))
            .where(Transaction.id.in_(candidate_ids))
        )
    }
    result = []
    for row in rows:
        candidate = candidates.get(row.duplicate_candidate_id)
        summary = (
            DuplicateCandidateRead(
                id=candidate.id,
                transaction_date=candidate.transaction_date,
                description=candidate.description,
                amount_minor=candidate.amount_minor,
                currency=candidate.currency,
                account_name=candidate.account.name,
            )
            if candidate
            else None
        )
        result.append(
            StagedRowRead.model_validate(row).model_copy(update={"duplicate_candidate": summary})
        )
    return result
