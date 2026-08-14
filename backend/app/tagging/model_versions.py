import logging
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from backend.app.database.models import ModelVersion
from backend.app.tagging.model import (
    _load_verified_model,
    current_taxonomy,
    verify_model_artifact,
)

logger = logging.getLogger(__name__)


class ModelLifecycleError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


def active_model(session: Session) -> ModelVersion | None:
    return session.scalar(select(ModelVersion).where(ModelVersion.is_active.is_(True)))


def candidate_model(session: Session) -> ModelVersion | None:
    return session.scalar(
        select(ModelVersion).where(
            ModelVersion.is_active.is_(False),
            ModelVersion.activated_at.is_(None),
            ModelVersion.retired_at.is_(None),
        )
    )


def previous_model(session: Session) -> ModelVersion | None:
    return session.scalar(
        select(ModelVersion)
        .where(
            ModelVersion.is_active.is_(False),
            ModelVersion.activated_at.is_not(None),
            ModelVersion.retired_at.is_(None),
        )
        .order_by(ModelVersion.activated_at.desc(), ModelVersion.created_at.desc())
        .limit(1)
    )


def activate_model(session: Session, data_dir: Path, model_version_id: str) -> ModelVersion:
    selected = session.get(ModelVersion, model_version_id)
    if selected is None:
        raise ModelLifecycleError("model_not_found", "Model version was not found")
    if selected.is_active:
        raise ModelLifecycleError("model_already_active", "Model version is already active")
    if selected.retired_at is not None:
        raise ModelLifecycleError(
            "model_artifact_retired", "Model version is retained for audit only"
        )

    candidate = candidate_model(session)
    if candidate is not None and candidate.id != selected.id:
        raise ModelLifecycleError(
            "pending_model_candidate",
            "Activate or reject the pending candidate before restoring a previous model",
        )
    previous = previous_model(session)
    is_candidate = selected.activated_at is None
    if not is_candidate and (previous is None or previous.id != selected.id):
        raise ModelLifecycleError(
            "model_not_available", "Only the retained previous model can be restored"
        )

    _verify_for_activation(session, data_dir, selected)
    activated_at = datetime.now(UTC)
    current = active_model(session)
    retired: ModelVersion | None = None
    if is_candidate and current is not None and previous is not None:
        previous.retired_at = activated_at
        retired = previous

    session.execute(
        update(ModelVersion)
        .where(ModelVersion.is_active.is_(True))
        .values(is_active=False)
        .execution_options(synchronize_session="fetch")
    )
    session.flush()
    selected.is_active = True
    selected.activated_at = activated_at
    selected.retired_at = None
    session.commit()
    _load_verified_model.cache_clear()
    if retired is not None:
        _delete_artifact(data_dir, retired)
    reconcile_model_artifacts(session, data_dir)
    return selected


def reject_candidate(session: Session, data_dir: Path, model_version_id: str) -> None:
    candidate = candidate_model(session)
    if candidate is None or candidate.id != model_version_id:
        raise ModelLifecycleError(
            "model_candidate_not_found", "Pending model candidate was not found"
        )
    artifact_path = _lexical_artifact_path(data_dir, candidate)
    deletion_path = artifact_path.with_name(f".{artifact_path.name}.delete")
    if artifact_path.exists() or artifact_path.is_symlink():
        try:
            artifact_path.replace(deletion_path)
        except OSError as exc:
            raise ModelLifecycleError(
                "model_artifact_delete_failed",
                "Candidate artifact could not be prepared for deletion",
            ) from exc
    try:
        session.delete(candidate)
        session.commit()
    except Exception:
        session.rollback()
        if deletion_path.exists() or deletion_path.is_symlink():
            deletion_path.replace(artifact_path)
        raise
    try:
        deletion_path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not finish deleting rejected model artifact %s", model_version_id)
    reconcile_model_artifacts(session, data_dir)


def reconcile_model_artifacts(session: Session, data_dir: Path) -> None:
    retired = list(
        session.scalars(select(ModelVersion).where(ModelVersion.retired_at.is_not(None)))
    )
    for model in retired:
        _delete_artifact(data_dir, model)
    models_dir = _models_dir(data_dir)
    if models_dir is None or not models_dir.is_dir():
        return
    referenced = {
        model.artifact_path
        for model in session.scalars(
            select(ModelVersion).where(ModelVersion.retired_at.is_(None))
        )
    }
    for artifact in models_dir.iterdir():
        relative_path = artifact.relative_to(data_dir.resolve()).as_posix()
        temporary = artifact.name.startswith(".") and artifact.suffix in {".tmp", ".delete"}
        orphaned = artifact.suffix == ".joblib" and relative_path not in referenced
        if not temporary and not orphaned:
            continue
        try:
            artifact.unlink(missing_ok=True)
        except OSError:
            logger.exception("Could not delete orphaned model artifact %s", artifact.name)


def _verify_for_activation(session: Session, data_dir: Path, model: ModelVersion) -> None:
    artifact_path = _artifact_path(data_dir, model)
    try:
        verified = verify_model_artifact(
            artifact_path,
            model.checksum,
            model.id,
            model.taxonomy_version,
            model.training_metadata,
        )
    except Exception as exc:
        raise ModelLifecycleError(
            "model_artifact_invalid", "Model artifact could not be verified"
        ) from exc
    if verified.taxonomy_checksum != current_taxonomy(session).checksum:
        raise ModelLifecycleError(
            "model_taxonomy_stale",
            "Taxonomy changed after this model was trained; retrain a new candidate",
        )


def _artifact_path(data_dir: Path, model: ModelVersion) -> Path:
    artifact_path = _lexical_artifact_path(data_dir, model)
    if artifact_path.is_symlink() or not artifact_path.is_file():
        raise ModelLifecycleError("model_artifact_invalid", "Model artifact is unavailable")
    return artifact_path


def _delete_artifact(data_dir: Path, model: ModelVersion) -> None:
    try:
        artifact_path = _lexical_artifact_path(data_dir, model)
    except ModelLifecycleError:
        logger.warning("Refusing to delete model %s with an invalid artifact path", model.id)
        return
    try:
        artifact_path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not delete retired model artifact for %s", model.id)


def _lexical_artifact_path(data_dir: Path, model: ModelVersion) -> Path:
    models_dir = _models_dir(data_dir)
    relative_path = Path(model.artifact_path)
    if models_dir is None or relative_path.is_absolute() or relative_path.suffix != ".joblib":
        raise ModelLifecycleError("model_artifact_invalid", "Model artifact path is invalid")
    artifact_path = data_dir.resolve() / relative_path
    if artifact_path.parent != models_dir:
        raise ModelLifecycleError("model_artifact_invalid", "Model artifact path is invalid")
    return artifact_path


def _models_dir(data_dir: Path) -> Path | None:
    models_dir = data_dir.resolve() / "models"
    if models_dir.is_symlink():
        logger.error("Refusing model artifact operations through a symlinked models directory")
        return None
    return models_dir
