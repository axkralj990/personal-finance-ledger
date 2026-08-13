from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from pydantic import ValidationError
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from backend.app.database.models import (
    Account,
    BatchStatus,
    Category,
    ImportBatch,
    ImportBatchExecutionPlan,
    ImportExecutionPlanKind,
    ImportMappingSuggestionAttempt,
    ImportMappingSuggestionOutcome,
    ImportMappingTemplate,
    ImportMappingTemplateOrigin,
    ImportMappingTemplateVersion,
    StagedDisposition,
    StagedTransaction,
    Subcategory,
    utc_now,
)
from backend.app.imports.inspection import InspectionError, inspect_file, read_source_rows
from backend.app.imports.mapping import (
    MappingError,
    generic_row_fingerprint,
    infer_universal_mapping,
    transform_file,
    transform_rows,
)
from backend.app.imports.models import ImportInspection, UniversalMappingSpec
from backend.app.imports.openai_mapping import (
    MappingFallbackCode,
    MappingFallbackError,
    MappingSuggestionFallback,
    MappingSuggestionResult,
    PreparedMappingPayload,
    prepare_mapping_payload,
)
from backend.app.imports.schemas import (
    MappedRowPreview,
    MappingPreviewRead,
    MappingProposals,
    TemplateProposal,
    TemplateRead,
    TemplateVersionRead,
)
from backend.app.imports.service import ImportService
from backend.app.problems import Problem

TERMINAL_STATUSES = {BatchStatus.COMMITTED, BatchStatus.FAILED, BatchStatus.DELETED}
STAGED_STATUSES = {BatchStatus.NEEDS_REVIEW, BatchStatus.READY, BatchStatus.PARSED}


class UniversalImportService:
    def __init__(self, max_rows: int, data_dir: Path) -> None:
        self.max_rows = max_rows
        self.data_dir = data_dir
        self.staging = ImportService(max_rows, data_dir)

    def create_upload(
        self,
        session: Session,
        account: Account,
        path: Path,
        original_filename: str,
        file_sha256: str,
    ) -> tuple[ImportBatch, bool]:
        existing = session.scalar(
            select(ImportBatch).where(
                ImportBatch.account_id == account.id,
                ImportBatch.file_sha256 == file_sha256,
                ImportBatch.status != BatchStatus.DELETED,
            )
        )
        if existing is not None:
            if existing.status == BatchStatus.COMMITTED:
                raise Problem(
                    409,
                    "duplicate_file_committed",
                    "This file was already committed for the destination account",
                    details={"batch_id": existing.id, "status": existing.status.value},
                )
            return existing, False

        try:
            inspection = inspect_file(path, max_rows=self.max_rows)
        except InspectionError as exc:
            batch = ImportBatch(
                account_id=account.id,
                original_filename=original_filename,
                retained_path=str(path),
                file_sha256=file_sha256,
                parser_version="universal-import-v1",
                status=BatchStatus.FAILED,
                error_message=str(exc),
            )
            session.add(batch)
            session.commit()
            raise Problem(
                422,
                "inspection_failed",
                str(exc),
                details={"batch_id": batch.id},
            ) from exc

        batch = ImportBatch(
            account_id=account.id,
            original_filename=original_filename,
            retained_path=str(path),
            file_sha256=file_sha256,
            parser_version="universal-import-v1",
            status=BatchStatus.AWAITING_MAPPING,
            inspection_json=inspection.model_dump(mode="json"),
            inspection_version=inspection.inspection_version,
            structural_signature=inspection.structural_signature,
            total_rows=inspection.row_count,
        )
        session.add(batch)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            winner = session.scalar(
                select(ImportBatch).where(
                    ImportBatch.account_id == account.id,
                    ImportBatch.file_sha256 == file_sha256,
                    ImportBatch.status != BatchStatus.DELETED,
                )
            )
            if winner is None:
                raise
            if winner.status == BatchStatus.COMMITTED:
                raise Problem(
                    409,
                    "duplicate_file_committed",
                    "This file was already committed",
                ) from exc
            return winner, False
        return batch, True

    def inspection(
        self, session: Session, batch: ImportBatch, offset: int, limit: int
    ) -> ImportInspection:
        current = self._inspection(batch)
        return inspect_file(
            self._source_path(batch),
            sheet=current.selected_sheet,
            header_row=current.header_row,
            preview_offset=offset,
            preview_limit=limit,
            max_rows=self.max_rows,
        )

    def update_inspection(
        self,
        session: Session,
        batch: ImportBatch,
        expected_revision: int,
        selected_sheet: str | int | None,
        header_row: int | None,
        offset: int,
        limit: int,
        confirm_restaging: bool = False,
    ) -> ImportInspection:
        self._mutable(batch, expected_revision)
        if batch.status == BatchStatus.STAGING:
            raise Problem(409, "staging_in_progress", "Inspection cannot change during staging")
        current = self._inspection(batch)
        if batch.staged_rows and not confirm_restaging:
            raise Problem(
                409,
                "restaging_confirmation_required",
                "Changing inspection would discard staged review work; confirm a new mapping first",
                recoverable=True,
            )
        inspection = inspect_file(
            self._source_path(batch),
            sheet=selected_sheet if selected_sheet is not None else current.selected_sheet,
            header_row=header_row if header_row is not None else current.header_row,
            preview_offset=offset,
            preview_limit=limit,
            max_rows=self.max_rows,
        )
        batch.inspection_json = inspection.model_dump(mode="json")
        batch.inspection_version = inspection.inspection_version
        batch.structural_signature = inspection.structural_signature
        batch.total_rows = inspection.row_count
        batch.current_mapping_origin = None
        batch.current_profile_id = None
        batch.current_profile_version = None
        batch.current_provider = None
        batch.current_fingerprint_algorithm = None
        batch.current_fingerprint_version = None
        batch.source_mapping_template_id = None
        batch.source_mapping_template_version_id = None
        if batch.staged_rows:
            session.execute(delete(StagedTransaction).where(StagedTransaction.batch_id == batch.id))
            session.expire(batch, ["staged_rows"])
        batch.status = BatchStatus.AWAITING_MAPPING
        batch.revision += 1
        batch.updated_at = utc_now()
        session.commit()
        return inspection

    def proposals(
        self, session: Session, batch: ImportBatch, inspection: ImportInspection
    ) -> MappingProposals:
        templates = list(
            session.scalars(
                select(ImportMappingTemplate)
                .options(selectinload(ImportMappingTemplate.versions))
                .where(
                    ImportMappingTemplate.structural_signature == inspection.structural_signature,
                    ImportMappingTemplate.is_active.is_(True),
                    (
                        (ImportMappingTemplate.account_id == batch.account_id)
                        | ImportMappingTemplate.account_id.is_(None)
                    ),
                )
                .order_by(
                    ImportMappingTemplate.account_id.is_(None),
                    ImportMappingTemplate.name,
                )
            )
        )
        template_proposals = []
        for template in templates:
            if not template.versions:
                continue
            try:
                plan = _plan_from_json(template.versions[-1].execution_plan_json)
            except ValidationError:
                continue
            template_proposals.append(
                TemplateProposal(
                    template_id=template.id,
                    template_version_id=template.versions[-1].id,
                    name=template.name,
                    scope="ACCOUNT" if template.account_id else "GLOBAL",
                    origin=template.origin,
                    execution_plan=plan,
                )
            )
        universal = infer_universal_mapping(
            inspection, default_currency=batch.account.default_currency
        )
        return MappingProposals(templates=template_proposals, universal=universal)

    def preview(
        self,
        batch: ImportBatch,
        plan: UniversalMappingSpec,
        offset: int,
        limit: int,
    ) -> MappingPreviewRead:
        inspection = self._inspection(batch)
        try:
            parsed = self._execute(batch, inspection, plan)
        except (MappingError, ValidationError, ValueError) as exc:
            raise Problem(422, "invalid_mapping", str(exc), recoverable=True) from exc
        return MappingPreviewRead(
            total_rows=len(parsed),
            importable_rows=sum(
                not row.issues and row.disposition != StagedDisposition.AUDIT_ONLY for row in parsed
            ),
            error_rows=sum(
                bool(row.issues) and row.disposition != StagedDisposition.AUDIT_ONLY
                for row in parsed
            ),
            audit_rows=sum(row.disposition == StagedDisposition.AUDIT_ONLY for row in parsed),
            rows=[
                MappedRowPreview(
                    row_number=row.row_number,
                    raw=row.raw,
                    transaction_date=(
                        row.transaction_date.isoformat() if row.transaction_date else None
                    ),
                    transaction_at=row.transaction_at.isoformat() if row.transaction_at else None,
                    description=row.description,
                    amount_minor=row.amount_minor,
                    currency=row.currency,
                    disposition=row.disposition.value,
                    issues=row.issues,
                )
                for row in parsed[offset : offset + limit]
            ],
        )

    def confirm_mapping(  # noqa: PLR0915 - validates and persists one immutable snapshot.
        self,
        session: Session,
        batch: ImportBatch,
        expected_revision: int,
        plan: UniversalMappingSpec,
        source_template_id: str | None,
        source_template_version_id: str | None,
        confirm_restaging: bool,
    ) -> ImportBatchExecutionPlan:
        self._mutable(batch, expected_revision)
        if batch.status == BatchStatus.STAGING:
            raise Problem(409, "staging_in_progress", "A staging operation is already active")
        if batch.staged_rows and not confirm_restaging:
            raise Problem(
                409,
                "restaging_confirmation_required",
                "Confirm that restaging may replace rows and discard review edits",
                recoverable=True,
            )
        inspection = self._inspection(batch)
        try:
            transform_rows([], inspection, plan)
        except (MappingError, ValidationError, ValueError) as exc:
            raise Problem(422, "invalid_mapping", str(exc), recoverable=True) from exc
        kind = ImportExecutionPlanKind.GUIDED_MAPPING
        fingerprint_algorithm = "generic-row-v1"
        fingerprint_version = "generic-normalization-v1"

        template = version = None
        if source_template_id is not None and source_template_version_id is not None:
            template = session.get(ImportMappingTemplate, source_template_id)
            if template is None or not template.is_active:
                raise Problem(
                    404,
                    "import_mapping_not_found",
                    "Active mapping template was not found",
                )
            if template.account_id not in {None, batch.account_id}:
                raise Problem(
                    422,
                    "mapping_scope_mismatch",
                    "Template is not global or scoped to this destination account",
                )
            if template.structural_signature != inspection.structural_signature:
                raise Problem(
                    422,
                    "mapping_signature_mismatch",
                    "Template does not match this structure",
                )
            version = next(
                (item for item in template.versions if item.id == source_template_version_id), None
            )
            if version is None:
                raise Problem(
                    404,
                    "import_mapping_version_not_found",
                    "The selected mapping template version was not found",
                )
            try:
                template_plan = _plan_from_json(version.execution_plan_json)
            except ValidationError as exc:
                raise Problem(
                    422,
                    "historical_mapping_not_executable",
                    "Historical adapter mappings cannot be selected or remapped",
                ) from exc
            if template_plan != plan:
                raise Problem(
                    422,
                    "mapping_template_plan_mismatch",
                    "Plan differs from the template version",
                )
            origin = template.origin
        elif self._is_current_suggestion(session, batch, plan):
            origin = ImportMappingTemplateOrigin.LLM_CONFIRMED
        else:
            origin = ImportMappingTemplateOrigin.MANUAL

        mapping_revision = batch.mapping_revision + 1
        snapshot = ImportBatchExecutionPlan(
            batch_id=batch.id,
            mapping_revision=mapping_revision,
            kind=kind,
            schema_version=plan.schema_version,
            plan_json=plan.model_dump(mode="json"),
            origin=origin,
            source_template_id=template.id if template else None,
            source_template_version_id=version.id if version else None,
            profile_id=None,
            profile_version=None,
            provider=None,
            fingerprint_algorithm=fingerprint_algorithm,
            fingerprint_version=fingerprint_version,
        )
        session.add(snapshot)
        session.flush()
        batch.mapping_revision = mapping_revision
        batch.current_mapping_origin = origin
        batch.current_profile_id = None
        batch.current_profile_version = None
        batch.current_provider = None
        batch.current_fingerprint_algorithm = fingerprint_algorithm
        batch.current_fingerprint_version = fingerprint_version
        batch.source_mapping_template_id = template.id if template else None
        batch.source_mapping_template_version_id = version.id if version else None
        batch.status = BatchStatus.AWAITING_MAPPING
        batch.revision += 1
        batch.updated_at = utc_now()
        session.commit()
        return snapshot

    def stage(  # noqa: PLR0915 - staging spans persisted and atomic replacement phases.
        self,
        session: Session,
        batch: ImportBatch,
        expected_revision: int,
        expected_mapping_revision: int,
    ) -> ImportBatch:
        self._mutable(batch, expected_revision)
        if batch.status == BatchStatus.STAGING:
            raise Problem(409, "staging_in_progress", "A staging operation is already active")
        if batch.mapping_revision != expected_mapping_revision:
            self._revision_conflict(batch, "The confirmed mapping changed")
        if batch.current_mapping_origin is None:
            raise Problem(409, "mapping_not_confirmed", "Confirm a mapping before staging")
        snapshot = session.scalar(
            select(ImportBatchExecutionPlan).where(
                ImportBatchExecutionPlan.batch_id == batch.id,
                ImportBatchExecutionPlan.mapping_revision == expected_mapping_revision,
            )
        )
        if snapshot is None:
            raise Problem(409, "mapping_not_confirmed", "Confirm a mapping before staging")
        if snapshot.kind != ImportExecutionPlanKind.GUIDED_MAPPING:
            raise Problem(
                409,
                "historical_mapping_not_executable",
                "Historical adapter mappings cannot be staged or replayed",
            )
        batch.status = BatchStatus.STAGING
        batch.revision += 1
        batch.error_message = None
        batch.updated_at = utc_now()
        session.commit()
        staging_revision = batch.revision

        try:
            inspection = self._inspection(batch)
            plan = _plan_from_json(snapshot.plan_json)
            parsed = self._execute(batch, inspection, plan, session=session)
            importable = [
                row
                for row in parsed
                if not row.issues and row.disposition != StagedDisposition.AUDIT_ONLY
            ]
            _require_importable_rows(importable)
        except (InspectionError, MappingError, ValidationError, ValueError) as exc:
            session.rollback()
            current = session.get(ImportBatch, batch.id)
            current.status = BatchStatus.AWAITING_MAPPING
            current.current_mapping_diagnostics = [
                {"code": "staging_failed", "message": str(exc), "retryable": True}
            ]
            current.error_message = str(exc)
            current.revision += 1
            current.updated_at = utc_now()
            session.commit()
            raise Problem(422, "staging_failed", str(exc), recoverable=True) from exc

        current = session.get(ImportBatch, batch.id)
        if current.status != BatchStatus.STAGING or current.revision != staging_revision:
            self._revision_conflict(current, "The batch changed while rows were being staged")
        session.execute(delete(StagedTransaction).where(StagedTransaction.batch_id == current.id))
        session.expire(current, ["staged_rows"])
        try:
            self.staging._stage_rows(
                session,
                current,
                current.account,
                parsed,
                fingerprint=lambda row, _account, _canonical: generic_row_fingerprint(
                    inspection.structural_signature, row.raw
                ),
                commit=False,
            )
            current.current_mapping_diagnostics = []
            current.error_message = None
            current.revision += 1
            session.commit()
        except Exception:
            session.rollback()
            interrupted = session.get(ImportBatch, batch.id)
            interrupted.status = BatchStatus.AWAITING_MAPPING
            interrupted.current_mapping_diagnostics = [
                {
                    "code": "staging_failed",
                    "message": "Rows could not be staged atomically",
                    "retryable": True,
                }
            ]
            interrupted.error_message = "Rows could not be staged atomically"
            interrupted.revision += 1
            interrupted.updated_at = utc_now()
            session.commit()
            raise
        return current

    def suggestion_payload(self, batch: ImportBatch) -> PreparedMappingPayload:
        inspection = self._inspection(batch)
        rows = read_source_rows(self._source_path(batch), inspection, max_rows=self.max_rows)
        return prepare_mapping_payload(inspection, rows)

    def validate_suggestion(
        self, batch: ImportBatch, result: MappingSuggestionResult
    ) -> MappingSuggestionResult:
        if result.status != "suggested":
            return result
        inspection = self._inspection(batch)
        try:
            parsed = transform_rows(inspection.preview, inspection, result.plan)
        except (MappingError, ValidationError, ValueError):
            parsed = []
        if any(
            not row.issues and row.disposition != StagedDisposition.AUDIT_ONLY for row in parsed
        ):
            return result
        return MappingSuggestionFallback(
            error=MappingFallbackError(
                code=MappingFallbackCode.INVALID_RESPONSE,
                message=(
                    "The mapping suggestion did not parse the local preview; continue manually."
                ),
                retryable=False,
            ),
            audit=result.audit.model_copy(
                update={
                    "outcome": "manual_fallback",
                    "error_code": MappingFallbackCode.INVALID_RESPONSE,
                }
            ),
        )

    def record_suggestion(
        self,
        session: Session,
        batch_id: str,
        expected_revision: int,
        result: MappingSuggestionResult,
    ) -> tuple[ImportBatch, bool]:
        batch = session.get(ImportBatch, batch_id)
        if batch is None or batch.status == BatchStatus.DELETED:
            raise Problem(404, "import_not_found", "Import batch was not found")
        stale = batch.revision != expected_revision
        audit = result.audit
        outcome = (
            ImportMappingSuggestionOutcome.STALE
            if stale
            else _suggestion_outcome(result.status, audit.error_code)
        )
        attempt_number = (
            select(func.coalesce(func.max(ImportMappingSuggestionAttempt.attempt_number), 0) + 1)
            .where(ImportMappingSuggestionAttempt.batch_id == batch.id)
            .scalar_subquery()
        )
        completed_at = datetime.now(UTC)
        session.add(
            ImportMappingSuggestionAttempt(
                batch_id=batch.id,
                batch_revision=expected_revision,
                attempt_number=attempt_number,  # type: ignore[arg-type]
                model_name=audit.model,
                provider_request_id=audit.request_id,
                prompt_version=audit.prompt_version,
                schema_version=audit.schema_version,
                payload_sha256=audit.payload_sha256,
                consented_at=audit.consented_at,
                started_at=audit.requested_at,
                completed_at=completed_at,
                duration_ms=audit.duration_ms,
                outcome=outcome,
                execution_plan_json=(
                    result.plan.model_dump(mode="json") if result.status == "suggested" else None
                ),
                error_class=(
                    result.error.code.value if result.status == "manual_fallback" else None
                ),
            )
        )
        if not stale and result.status == "suggested":
            batch.revision += 1
            batch.updated_at = utc_now()
        session.commit()
        return batch, stale

    @staticmethod
    def _is_current_suggestion(
        session: Session, batch: ImportBatch, plan: UniversalMappingSpec
    ) -> bool:
        suggestion = session.scalar(
            select(ImportMappingSuggestionAttempt)
            .where(
                ImportMappingSuggestionAttempt.batch_id == batch.id,
                ImportMappingSuggestionAttempt.outcome == ImportMappingSuggestionOutcome.SUCCEEDED,
            )
            .order_by(ImportMappingSuggestionAttempt.attempt_number.desc())
            .limit(1)
        )
        return bool(
            suggestion
            and suggestion.batch_revision + 1 == batch.revision
            and suggestion.execution_plan_json is not None
            and _plan_from_json(suggestion.execution_plan_json) == plan
        )

    @staticmethod
    def recover_staging(session: Session) -> int:
        batches = list(
            session.scalars(select(ImportBatch).where(ImportBatch.status == BatchStatus.STAGING))
        )
        for batch in batches:
            session.execute(delete(StagedTransaction).where(StagedTransaction.batch_id == batch.id))
            batch.status = BatchStatus.AWAITING_MAPPING
            batch.current_mapping_diagnostics = [
                {
                    "code": "staging_interrupted",
                    "message": "Staging was interrupted and can be retried",
                    "retryable": True,
                }
            ]
            batch.error_message = "Staging was interrupted and can be retried"
            batch.revision += 1
            batch.updated_at = utc_now()
        if batches:
            session.commit()
        return len(batches)

    def _execute(
        self,
        batch: ImportBatch,
        inspection: ImportInspection,
        plan: UniversalMappingSpec,
        *,
        session: Session | None = None,
    ):
        resolver = self._taxonomy_resolver(session) if session is not None else None
        return transform_file(
            self._source_path(batch),
            inspection,
            plan,
            max_rows=self.max_rows,
            taxonomy_resolver=resolver,
        )

    @staticmethod
    def _taxonomy_resolver(session: Session):
        def resolve(category_value: str, subcategory_value: str | None):
            category_key = category_value.strip().casefold()
            categories = list(session.scalars(select(Category).where(Category.is_active.is_(True))))
            category = next(
                (
                    item
                    for item in categories
                    if category_key in {item.slug.casefold(), item.display_name.strip().casefold()}
                ),
                None,
            )
            if category is None:
                return None
            if not subcategory_value or not subcategory_value.strip():
                return category.id, None
            subcategory_key = subcategory_value.strip().casefold()
            subcategory = session.scalar(
                select(Subcategory).where(
                    Subcategory.category_id == category.id,
                    Subcategory.is_active.is_(True),
                    (
                        (func.lower(Subcategory.slug) == subcategory_key)
                        | (func.lower(Subcategory.display_name) == subcategory_key)
                    ),
                )
            )
            return (category.id, subcategory.id) if subcategory else None

        return resolve

    @staticmethod
    def _inspection(batch: ImportBatch) -> ImportInspection:
        try:
            return ImportInspection.model_validate_json(json.dumps(batch.inspection_json))
        except ValidationError as exc:
            raise Problem(
                409,
                "inspection_unavailable",
                "Import inspection is unavailable",
            ) from exc

    @staticmethod
    def _source_path(batch: ImportBatch) -> Path:
        if not batch.retained_path:
            raise Problem(409, "source_file_unavailable", "Import has no retained source file")
        path = Path(batch.retained_path)
        if not path.is_file():
            raise Problem(410, "source_file_missing", "Retained source file is missing")
        return path

    @staticmethod
    def _mutable(batch: ImportBatch, expected_revision: int) -> None:
        if batch.status in TERMINAL_STATUSES:
            raise Problem(409, "terminal_import", "Terminal imports cannot be changed")
        if batch.revision != expected_revision:
            UniversalImportService._revision_conflict(
                batch, "The import changed since it was loaded"
            )

    @staticmethod
    def _revision_conflict(batch: ImportBatch, message: str) -> None:
        raise Problem(
            409,
            "revision_conflict",
            message,
            recoverable=True,
            details={"current_revision": batch.revision},
        )


class ImportMappingTemplateService:
    def list(
        self,
        session: Session,
        *,
        account_id: str | None,
        structural_signature: str | None,
        include_inactive: bool,
    ) -> list[TemplateRead]:
        statement = select(ImportMappingTemplate).options(
            selectinload(ImportMappingTemplate.versions)
        )
        if account_id is not None:
            statement = statement.where(
                (ImportMappingTemplate.account_id == account_id)
                | ImportMappingTemplate.account_id.is_(None)
            ).order_by(
                ImportMappingTemplate.account_id.is_(None),
                ImportMappingTemplate.name,
            )
        else:
            statement = statement.order_by(ImportMappingTemplate.name)
        if structural_signature is not None:
            statement = statement.where(
                ImportMappingTemplate.structural_signature == structural_signature
            )
        if not include_inactive:
            statement = statement.where(ImportMappingTemplate.is_active.is_(True))
        mappings = []
        for template in session.scalars(statement):
            try:
                mappings.append(self.read(template, include_versions=False))
            except Problem as exc:
                if exc.body.code != "import_mapping_not_found":
                    raise
        return mappings

    def create(
        self,
        session: Session,
        *,
        name: str,
        structural_signature: str,
        account_id: str | None,
        plan: UniversalMappingSpec,
        source_batch_id: str | None,
        source_batch_revision: int | None,
    ) -> ImportMappingTemplate:
        if account_id is not None and session.get(Account, account_id) is None:
            raise Problem(404, "account_not_found", "Account was not found")
        origin = ImportMappingTemplateOrigin.MANUAL
        if source_batch_id is not None and source_batch_revision is not None:
            batch = session.get(ImportBatch, source_batch_id)
            if batch is None or batch.status == BatchStatus.DELETED:
                raise Problem(404, "import_not_found", "Source import batch was not found")
            if batch.revision != source_batch_revision:
                UniversalImportService._revision_conflict(
                    batch, "The source import changed since it was loaded"
                )
            if account_id is not None and account_id != batch.account_id:
                raise Problem(
                    422,
                    "mapping_scope_mismatch",
                    "An account mapping must use the source import's destination account",
                )
            if not UniversalImportService._is_current_suggestion(session, batch, plan):
                raise Problem(
                    422,
                    "suggestion_not_current",
                    "LLM mapping provenance requires the current successful suggestion",
                )
            if structural_signature != batch.structural_signature:
                raise Problem(
                    422,
                    "mapping_signature_mismatch",
                    "Template structure differs from the source import",
                )
            origin = ImportMappingTemplateOrigin.LLM_CONFIRMED
        template = ImportMappingTemplate(
            name=name.strip(),
            structural_signature=structural_signature,
            account_id=account_id,
            origin=origin,
            is_active=True,
        )
        session.add(template)
        session.flush()
        session.add(self._version(template, 1, plan))
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise Problem(
                409,
                "mapping_name_conflict",
                "A mapping with this name already exists",
            ) from exc
        return template

    def patch(
        self,
        session: Session,
        template: ImportMappingTemplate,
        *,
        expected_revision: int,
        name: str | None,
        is_active: bool | None,
        plan: UniversalMappingSpec | None,
    ) -> ImportMappingTemplate:
        if template.revision != expected_revision:
            raise Problem(
                409,
                "revision_conflict",
                "The mapping changed since it was loaded",
                recoverable=True,
                details={"current_revision": template.revision},
            )
        try:
            _plan_from_json(template.versions[-1].execution_plan_json)
        except ValidationError as exc:
            raise Problem(
                409,
                "historical_mapping_not_editable",
                "Historical adapter mapping templates cannot be edited",
            ) from exc
        if template.origin == ImportMappingTemplateOrigin.PREDEFINED:
            raise Problem(
                409,
                "predefined_mapping_immutable",
                "Predefined mappings cannot be edited",
            )
        if name is not None:
            template.name = name.strip()
        if is_active is not None:
            template.is_active = is_active
        if plan is not None:
            session.add(self._version(template, len(template.versions) + 1, plan))
        template.revision += 1
        template.updated_at = utc_now()
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise Problem(
                409,
                "mapping_name_conflict",
                "A mapping with this name already exists",
            ) from exc
        session.expire(template, ["versions"])
        return template

    @staticmethod
    def get(session: Session, template_id: str) -> ImportMappingTemplate:
        template = session.scalar(
            select(ImportMappingTemplate)
            .options(selectinload(ImportMappingTemplate.versions))
            .where(ImportMappingTemplate.id == template_id)
        )
        if template is None:
            raise Problem(404, "import_mapping_not_found", "Mapping template was not found")
        return template

    @staticmethod
    def read(template: ImportMappingTemplate, *, include_versions: bool) -> TemplateRead:
        versions = []
        for version in template.versions:
            try:
                plan = _plan_from_json(version.execution_plan_json)
            except ValidationError:
                continue
            versions.append(
                TemplateVersionRead(
                    id=version.id,
                    version=version.version,
                    execution_plan=plan,
                    created_at=version.created_at,
                )
            )
        if not versions:
            raise Problem(
                404,
                "import_mapping_not_found",
                "No active universal version exists for this mapping template",
            )
        return TemplateRead(
            id=template.id,
            name=template.name,
            structural_signature=template.structural_signature,
            account_id=template.account_id,
            origin=template.origin,
            is_active=template.is_active,
            revision=template.revision,
            created_at=template.created_at,
            updated_at=template.updated_at,
            current_version=versions[-1],
            versions=versions if include_versions else [],
        )

    @staticmethod
    def _version(
        template: ImportMappingTemplate, version: int, plan: UniversalMappingSpec
    ) -> ImportMappingTemplateVersion:
        return ImportMappingTemplateVersion(
            template_id=template.id,
            version=version,
            execution_plan_kind=ImportExecutionPlanKind.GUIDED_MAPPING,
            execution_plan_schema_version=plan.schema_version,
            execution_plan_json=plan.model_dump(mode="json"),
        )


def _suggestion_outcome(
    status: str, code: MappingFallbackCode | None
) -> ImportMappingSuggestionOutcome:
    if status == "suggested":
        return ImportMappingSuggestionOutcome.SUCCEEDED
    mapping = {
        MappingFallbackCode.AUTHENTICATION: ImportMappingSuggestionOutcome.AUTHENTICATION_ERROR,
        MappingFallbackCode.PERMISSION: ImportMappingSuggestionOutcome.PERMISSION_ERROR,
        MappingFallbackCode.CONNECTION: ImportMappingSuggestionOutcome.CONNECTION_ERROR,
        MappingFallbackCode.TIMEOUT: ImportMappingSuggestionOutcome.TIMEOUT,
        MappingFallbackCode.PROVIDER_RATE_LIMIT: ImportMappingSuggestionOutcome.RATE_LIMITED,
        MappingFallbackCode.LOCAL_RATE_LIMIT: ImportMappingSuggestionOutcome.RATE_LIMITED,
        MappingFallbackCode.CONCURRENCY_LIMIT: ImportMappingSuggestionOutcome.RATE_LIMITED,
        MappingFallbackCode.REFUSAL: ImportMappingSuggestionOutcome.REFUSED,
        MappingFallbackCode.INVALID_RESPONSE: ImportMappingSuggestionOutcome.INVALID_OUTPUT,
    }
    return mapping.get(code, ImportMappingSuggestionOutcome.PROVIDER_ERROR)


def _require_importable_rows(rows: list) -> None:
    if not rows:
        raise MappingError("mapping produced no importable rows")


def _plan_from_json(value: dict) -> UniversalMappingSpec:
    return UniversalMappingSpec.model_validate_json(json.dumps(value))
