from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, ConfigDict

from backend.app.api.dependencies import SessionDependency
from backend.app.database.models import ModelVersion
from backend.app.problems import Problem
from backend.app.tagging.model import current_taxonomy
from backend.app.tagging.model_versions import (
    ModelLifecycleError,
    activate_model,
    active_model,
    candidate_model,
    previous_model,
    reject_candidate,
)
from backend.app.tagging.training import PendingCandidateError, TrainingError, train_model

router = APIRouter(prefix="/tagging/models", tags=["tagging models"])
ModelStatus = Literal["ACTIVE", "CANDIDATE", "PREVIOUS"]


class CrossValidationRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    requested_folds: int
    effective_folds: int
    evaluated_row_count: int
    category_accuracy: float
    exact_match_accuracy: float
    auto_accept_coverage: float
    auto_accept_accuracy: float | None


class ModelVersionRead(BaseModel):
    model_version_id: str
    model_name: str
    status: ModelStatus
    created_at: datetime
    activated_at: datetime | None
    training_row_count: int
    category_count: int
    subcategory_model_count: int
    subcategory_constant_count: int
    category_threshold: float
    subcategory_threshold: float
    evaluation_schema_version: str | None
    training_data_checksum: str | None
    taxonomy_current: bool
    cross_validation: CrossValidationRead | None


class ModelOverviewRead(BaseModel):
    active: ModelVersionRead | None
    candidate: ModelVersionRead | None
    previous: ModelVersionRead | None


@router.get("", response_model=ModelOverviewRead)
def get_models(session: SessionDependency) -> ModelOverviewRead:
    taxonomy_checksum = current_taxonomy(session).checksum
    return ModelOverviewRead(
        active=_read_optional(active_model(session), "ACTIVE", taxonomy_checksum),
        candidate=_read_optional(candidate_model(session), "CANDIDATE", taxonomy_checksum),
        previous=_read_optional(previous_model(session), "PREVIOUS", taxonomy_checksum),
    )


@router.get("/active", response_model=ModelVersionRead | None)
def get_active_model(session: SessionDependency) -> ModelVersionRead | None:
    model = active_model(session)
    return _read_optional(model, "ACTIVE", current_taxonomy(session).checksum)


@router.post("/retrain", response_model=ModelVersionRead, status_code=201)
def retrain_model(request: Request, session: SessionDependency) -> ModelVersionRead:
    if candidate_model(session) is not None:
        raise Problem(
            409,
            "pending_model_candidate",
            "Activate or reject the pending candidate before retraining",
            recoverable=True,
        )
    try:
        result = train_model(session, request.app.state.settings.data_dir)
    except PendingCandidateError as exc:
        raise Problem(
            409,
            "pending_model_candidate",
            str(exc),
            recoverable=True,
        ) from exc
    except TrainingError as exc:
        raise Problem(
            422,
            "model_training_failed",
            str(exc),
            recoverable=True,
        ) from exc
    model = session.get(ModelVersion, result.model_version_id)
    if model is None:
        raise RuntimeError("candidate model metadata was not persisted")
    return _read_model(model, "CANDIDATE", current_taxonomy(session).checksum)


@router.post("/{model_version_id}/activate", response_model=ModelVersionRead)
def activate_model_version(
    model_version_id: str, request: Request, session: SessionDependency
) -> ModelVersionRead:
    try:
        model = activate_model(
            session,
            request.app.state.settings.data_dir,
            model_version_id,
        )
    except ModelLifecycleError as exc:
        raise _lifecycle_problem(exc) from exc
    return _read_model(model, "ACTIVE", current_taxonomy(session).checksum)


@router.delete("/{model_version_id}", status_code=204)
def reject_model_version(
    model_version_id: str, request: Request, session: SessionDependency
) -> Response:
    try:
        reject_candidate(
            session,
            request.app.state.settings.data_dir,
            model_version_id,
        )
    except ModelLifecycleError as exc:
        raise _lifecycle_problem(exc) from exc
    return Response(status_code=204)


def _read_optional(
    model: ModelVersion | None, status: ModelStatus, taxonomy_checksum: str
) -> ModelVersionRead | None:
    return _read_model(model, status, taxonomy_checksum) if model is not None else None


def _read_model(
    model: ModelVersion, status: ModelStatus, taxonomy_checksum: str
) -> ModelVersionRead:
    metadata: dict[str, Any] = model.training_metadata
    thresholds = metadata.get("thresholds", {})
    cross_validation = metadata.get("cross_validation")
    return ModelVersionRead(
        model_version_id=model.id,
        model_name=model.name,
        status=status,
        created_at=_utc_datetime(model.created_at),
        activated_at=_utc_datetime(model.activated_at) if model.activated_at else None,
        training_row_count=int(metadata.get("training_row_count", 0)),
        category_count=int(metadata.get("category_count", 0)),
        subcategory_model_count=int(metadata.get("subcategory_model_count", 0)),
        subcategory_constant_count=int(metadata.get("subcategory_constant_count", 0)),
        category_threshold=float(thresholds.get("category", 0.7)),
        subcategory_threshold=float(thresholds.get("subcategory", 0.8)),
        evaluation_schema_version=metadata.get("evaluation_schema_version"),
        training_data_checksum=metadata.get("training_data_checksum"),
        taxonomy_current=metadata.get("taxonomy_checksum") == taxonomy_checksum,
        cross_validation=(
            CrossValidationRead.model_validate(cross_validation)
            if isinstance(cross_validation, dict)
            else None
        ),
    )


def _lifecycle_problem(exc: ModelLifecycleError) -> Problem:
    status_code = 404 if exc.code in {"model_not_found", "model_candidate_not_found"} else 409
    return Problem(status_code, exc.code, str(exc), recoverable=True)


def _utc_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
