import hashlib
import uuid
from datetime import date, datetime
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, joinedload

from backend.app.api.dependencies import SessionDependency
from backend.app.api.pagination import Page
from backend.app.database.models import (
    BatchStatus,
    DuplicateStatus,
    ImportBatch,
    SourceAccount,
    StagedDisposition,
    StagedTransaction,
    Transaction,
    TransactionKind,
)
from backend.app.imports.service import ImportService
from backend.app.problems import Problem

router = APIRouter(tags=["imports"])


class BatchRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    source_account_id: str
    original_filename: str
    file_sha256: str
    parser_version: str
    status: BatchStatus
    total_rows: int
    valid_rows: int = 0
    needs_review_rows: int = 0
    duplicate_rows: int = 0
    included_rows: int
    ignored_rows: int
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
    source_account_name: str


class StagedRowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    ledger_account_id: str
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


class BulkStagedPatch(BaseModel):
    rows: list[StagedRowPatch] = Field(min_length=1)


class ManualRow(BaseModel):
    transaction_date: date
    description: str = Field(min_length=1)
    amount_minor: int
    currency: str | None = Field(default=None, min_length=3, max_length=3)
    category_id: str | None = None
    subcategory_id: str | None = None


class ManualImportCreate(BaseModel):
    source_account_id: str
    rows: list[ManualRow] = Field(min_length=1)


@router.post("/imports", response_model=BatchRead, status_code=201)
async def create_import(
    request: Request,
    session: SessionDependency,
    source_account_id: Annotated[str, Form()],
    file: Annotated[UploadFile, File()],
) -> BatchRead:
    account = session.get(SourceAccount, source_account_id)
    if account is None or not account.is_active:
        raise Problem(404, "source_account_not_found", "Active source account was not found")
    uploads = request.app.state.settings.data_dir / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "upload").suffix.casefold()
    retained_path = uploads / f"{uuid.uuid4()}{suffix}"
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
    service = ImportService(
        request.app.state.settings.max_file_rows, request.app.state.settings.data_dir
    )
    try:
        batch = service.stage_file(
            session, account, retained_path, file.filename or "upload", digest.hexdigest()
        )
        return _batch_reads(session, [batch])[0]
    except Problem as exc:
        if exc.body.code == "duplicate_file":
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
    ).update_rows(session, batch, changes)
    return _staged_row_reads(session, updated)


@router.post("/imports/{batch_id}/commit", response_model=BatchRead)
def commit_import(batch_id: str, request: Request, session: SessionDependency) -> BatchRead:
    batch = _batch(session, batch_id)
    ImportService(
        request.app.state.settings.max_file_rows, request.app.state.settings.data_dir
    ).commit(session, batch)
    return _batch_reads(session, [batch])[0]


@router.delete("/imports/{batch_id}", status_code=204)
def delete_import(batch_id: str, session: SessionDependency) -> None:
    batch = _draft_batch(session, batch_id)
    batch.status = BatchStatus.DELETED
    session.commit()


@router.post("/manual-imports", response_model=BatchRead, status_code=201)
def create_manual_import(
    payload: ManualImportCreate, request: Request, session: SessionDependency
) -> BatchRead:
    account = session.get(SourceAccount, payload.source_account_id)
    if account is None or not account.is_active:
        raise Problem(404, "source_account_not_found", "Active source account was not found")
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
    if batch.status == BatchStatus.COMMITTED:
        raise Problem(409, "import_already_committed", "Committed imports cannot be changed")
    return batch


def _raise_file_too_large() -> Any:
    raise Problem(413, "file_too_large", "Upload exceeds the configured size limit")


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
        )
        .where(StagedTransaction.batch_id.in_(batch_ids))
        .group_by(StagedTransaction.batch_id)
    )
    counts = {
        batch_id: (int(valid or 0), int(needs_review or 0), int(duplicates or 0))
        for batch_id, valid, needs_review, duplicates in aggregate_rows
    }
    return [
        BatchRead.model_validate(batch).model_copy(
            update={
                "valid_rows": counts.get(batch.id, (0, 0, 0))[0],
                "needs_review_rows": counts.get(batch.id, (0, 0, 0))[1],
                "duplicate_rows": counts.get(batch.id, (0, 0, 0))[2],
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
                source_account_name=candidate.account.display_name,
            )
            if candidate
            else None
        )
        result.append(
            StagedRowRead.model_validate(row).model_copy(update={"duplicate_candidate": summary})
        )
    return result
