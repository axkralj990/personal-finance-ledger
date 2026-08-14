import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import joblib
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import FeatureUnion, Pipeline
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.database.models import Category, ModelVersion, Transaction
from backend.app.tagging.evaluation import (
    CrossValidationMetrics,
    TrainingExample,
    cross_validate_hierarchy,
    fit_hierarchy,
)
from backend.app.tagging.model import (
    ARTIFACT_SCHEMA_VERSION,
    current_taxonomy,
    verify_model_artifact,
)

DEFAULT_CATEGORY_THRESHOLD = 0.70
DEFAULT_SUBCATEGORY_THRESHOLD = 0.80
RANDOM_STATE = 42
DEFAULT_CROSS_VALIDATION_FOLDS = 5
EVALUATION_SCHEMA_VERSION = "grouped-hierarchy-v1"


class TrainingError(ValueError):
    pass


class PendingCandidateError(TrainingError):
    pass


@dataclass(frozen=True, slots=True)
class TrainingResult:
    model_version_id: str
    model_name: str
    training_row_count: int
    category_count: int
    subcategory_model_count: int
    subcategory_constant_count: int
    checksum: str
    sklearn_version: str
    taxonomy_version: str
    cross_validation: CrossValidationMetrics


def train_model(
    session: Session,
    data_dir: Path,
    *,
    category_threshold: float = DEFAULT_CATEGORY_THRESHOLD,
    subcategory_threshold: float = DEFAULT_SUBCATEGORY_THRESHOLD,
) -> TrainingResult:
    _validate_threshold("category", category_threshold)
    _validate_threshold("subcategory", subcategory_threshold)
    candidate_id = session.scalar(
        select(ModelVersion.id).where(
            ModelVersion.is_active.is_(False),
            ModelVersion.activated_at.is_(None),
            ModelVersion.retired_at.is_(None),
        )
    )
    if candidate_id is not None:
        raise PendingCandidateError("a model candidate is already awaiting review")
    transactions = list(
        session.scalars(
            select(Transaction)
            .join(Category, Category.id == Transaction.category_id)
            .where(
                Transaction.is_excluded.is_(False),
                Transaction.category_id.is_not(None),
                func.length(func.trim(Transaction.normalized_description)) > 0,
                Category.is_active.is_(True),
            )
            .order_by(Transaction.id)
        )
    )
    if not transactions:
        raise TrainingError("no committed labeled transactions are available for training")

    taxonomy = current_taxonomy(session)
    examples = [
        TrainingExample(
            normalized_description=transaction.normalized_description,
            amount_minor=transaction.amount_minor,
            kind=transaction.kind,
            category_id=str(transaction.category_id),
            subcategory_id=(
                transaction.subcategory_id
                if taxonomy.subcategory_parents.get(transaction.subcategory_id)
                == str(transaction.category_id)
                else None
            ),
        )
        for transaction in transactions
    ]
    try:
        cross_validation = cross_validate_hierarchy(
            examples,
            _classifier,
            requested_folds=DEFAULT_CROSS_VALIDATION_FOLDS,
            category_threshold=category_threshold,
            subcategory_threshold=subcategory_threshold,
        )
        hierarchy = fit_hierarchy(examples, _classifier)
    except ValueError as exc:
        raise TrainingError(str(exc)) from exc

    created_at = datetime.now(UTC)
    model_version_id = str(uuid.uuid4())
    model_name = f"tagger-{created_at.strftime('%Y%m%dT%H%M%S%fZ')}-{model_version_id[:8]}"
    metadata: dict[str, Any] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_version_id": model_version_id,
        "created_at": created_at.isoformat(),
        "training_row_count": len(transactions),
        "category_count": len(hierarchy.category_counts),
        "category_labels": sorted(hierarchy.category_counts),
        "category_training_counts": hierarchy.category_counts,
        "subcategory_labels": {
            category_id: sorted(counts)
            for category_id, counts in hierarchy.subcategory_counts.items()
        },
        "subcategory_training_counts": hierarchy.subcategory_counts,
        "subcategory_model_count": len(hierarchy.subcategory_models),
        "subcategory_constant_count": len(hierarchy.subcategory_constants),
        "subcategory_unresolved_categories": hierarchy.unresolved_categories,
        "cross_validation": cross_validation.as_dict(),
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "training_data_checksum": _training_data_checksum(examples),
        "thresholds": {
            "category": category_threshold,
            "subcategory": subcategory_threshold,
        },
        "library_versions": {
            "joblib": joblib.__version__,
            "scikit_learn": sklearn.__version__,
        },
        "taxonomy_checksum": taxonomy.checksum,
        "taxonomy_version": taxonomy.version,
        "model_configuration": {
            "classifier": "OneVsRestClassifier(LogisticRegression)",
            "class_weight": "balanced",
            "max_iter": 2000,
            "random_state": RANDOM_STATE,
            "solver": "liblinear",
            "word_ngram_range": [1, 2],
            "character_analyzer": "char_wb",
            "character_ngram_range": [3, 5],
            "minimum_subcategory_class_rows": 2,
            "direction_feature": "signed_amount",
            "kind_feature": "transaction_kind",
        },
    }
    artifact = {
        "metadata": metadata,
        "category_model": hierarchy.category_model,
        "subcategory_models": hierarchy.subcategory_models,
        "subcategory_constants": hierarchy.subcategory_constants,
    }

    checksum = _persist_candidate(
        session,
        data_dir,
        model_version_id,
        model_name,
        created_at,
        metadata,
        artifact,
    )

    return TrainingResult(
        model_version_id=model_version_id,
        model_name=model_name,
        training_row_count=len(transactions),
        category_count=len(hierarchy.category_counts),
        subcategory_model_count=len(hierarchy.subcategory_models),
        subcategory_constant_count=len(hierarchy.subcategory_constants),
        checksum=checksum,
        sklearn_version=sklearn.__version__,
        taxonomy_version=taxonomy.version,
        cross_validation=cross_validation,
    )


def _classifier() -> Pipeline:
    features = FeatureUnion(
        [
            (
                "word",
                TfidfVectorizer(
                    ngram_range=(1, 2),
                    sublinear_tf=True,
                    strip_accents="unicode",
                ),
            ),
            (
                "character",
                TfidfVectorizer(
                    analyzer="char_wb",
                    ngram_range=(3, 5),
                    sublinear_tf=True,
                    strip_accents="unicode",
                ),
            ),
        ]
    )
    return Pipeline(
        [
            ("features", features),
            (
                "classifier",
                OneVsRestClassifier(
                    LogisticRegression(
                        class_weight="balanced",
                        max_iter=2000,
                        random_state=RANDOM_STATE,
                        solver="liblinear",
                    ),
                    n_jobs=1,
                ),
            ),
        ]
    )


def _persist_candidate(
    session: Session,
    data_dir: Path,
    model_version_id: str,
    model_name: str,
    created_at: datetime,
    metadata: dict[str, Any],
    artifact: dict[str, Any],
) -> str:
    resolved_data_dir = data_dir.resolve()
    models_dir = resolved_data_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    artifact_path = models_dir / f"{model_name}.joblib"
    temporary_path = models_dir / f".{model_name}.tmp"
    try:
        joblib.dump(artifact, temporary_path, compress=3)
        temporary_path.replace(artifact_path)
        checksum = _file_hash(artifact_path)
        verify_model_artifact(
            artifact_path,
            checksum,
            model_version_id,
            str(metadata["taxonomy_version"]),
            metadata,
        )
        session.add(
            ModelVersion(
                id=model_version_id,
                name=model_name,
                artifact_path=artifact_path.relative_to(resolved_data_dir).as_posix(),
                checksum=checksum,
                training_metadata=metadata,
                taxonomy_version=str(metadata["taxonomy_version"]),
                is_active=False,
                created_at=created_at,
                activated_at=None,
                retired_at=None,
            )
        )
        session.commit()
    except IntegrityError as exc:
        session.rollback()
        temporary_path.unlink(missing_ok=True)
        artifact_path.unlink(missing_ok=True)
        if session.scalar(
            select(ModelVersion.id).where(
                ModelVersion.is_active.is_(False),
                ModelVersion.activated_at.is_(None),
                ModelVersion.retired_at.is_(None),
            )
        ):
            raise PendingCandidateError(
                "a model candidate is already awaiting review"
            ) from exc
        raise
    except Exception:
        session.rollback()
        temporary_path.unlink(missing_ok=True)
        artifact_path.unlink(missing_ok=True)
        raise
    return checksum


def _validate_threshold(name: str, value: float) -> None:
    if not 0.0 < value <= 1.0:
        raise TrainingError(f"{name} confidence threshold must be greater than 0 and at most 1")


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _training_data_checksum(examples: list[TrainingExample]) -> str:
    payload = [
        {
            "amount_minor": example.amount_minor,
            "category_id": example.category_id,
            "kind": example.kind.value,
            "normalized_description": example.normalized_description,
            "subcategory_id": example.subcategory_id,
        }
        for example in examples
    ]
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
