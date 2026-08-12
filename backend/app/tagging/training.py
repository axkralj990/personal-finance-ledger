import hashlib
import uuid
from collections import Counter, defaultdict
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
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from backend.app.database.models import Category, ModelVersion, Transaction
from backend.app.tagging.model import (
    ARTIFACT_SCHEMA_VERSION,
    current_taxonomy,
    model_feature,
    verify_model_artifact,
)

DEFAULT_CATEGORY_THRESHOLD = 0.70
DEFAULT_SUBCATEGORY_THRESHOLD = 0.80
MIN_SUBCATEGORY_CLASS_ROWS = 2
RANDOM_STATE = 42


class TrainingError(ValueError):
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


def train_model(
    session: Session,
    data_dir: Path,
    *,
    category_threshold: float = DEFAULT_CATEGORY_THRESHOLD,
    subcategory_threshold: float = DEFAULT_SUBCATEGORY_THRESHOLD,
) -> TrainingResult:
    _validate_threshold("category", category_threshold)
    _validate_threshold("subcategory", subcategory_threshold)
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

    category_labels = [str(transaction.category_id) for transaction in transactions]
    category_counts = Counter(category_labels)
    if len(category_counts) < 2:
        raise TrainingError("at least two category classes are required for training")

    taxonomy = current_taxonomy(session)
    features = [
        model_feature(
            transaction.normalized_description,
            transaction.amount_minor,
            transaction.kind,
        )
        for transaction in transactions
    ]
    category_model = _classifier().fit(features, category_labels)

    subcategory_rows: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for transaction, feature in zip(transactions, features, strict=True):
        subcategory_id = transaction.subcategory_id
        category_id = str(transaction.category_id)
        if (
            subcategory_id is not None
            and taxonomy.subcategory_parents.get(subcategory_id) == category_id
        ):
            subcategory_rows[category_id].append((feature, subcategory_id))

    subcategory_models: dict[str, Any] = {}
    subcategory_constants: dict[str, str] = {}
    subcategory_counts: dict[str, dict[str, int]] = {}
    unresolved_categories: list[str] = []
    for category_id in sorted(subcategory_rows):
        rows = subcategory_rows[category_id]
        counts = Counter(label for _, label in rows)
        subcategory_counts[category_id] = dict(sorted(counts.items()))
        if len(counts) == 1:
            subcategory_constants[category_id] = next(iter(counts))
        elif min(counts.values()) >= MIN_SUBCATEGORY_CLASS_ROWS:
            subcategory_models[category_id] = _classifier().fit(
                [feature for feature, _ in rows], [label for _, label in rows]
            )
        else:
            unresolved_categories.append(category_id)

    created_at = datetime.now(UTC)
    model_version_id = str(uuid.uuid4())
    model_name = f"tagger-{created_at.strftime('%Y%m%dT%H%M%S%fZ')}-{model_version_id[:8]}"
    metadata: dict[str, Any] = {
        "artifact_schema_version": ARTIFACT_SCHEMA_VERSION,
        "model_version_id": model_version_id,
        "created_at": created_at.isoformat(),
        "training_row_count": len(transactions),
        "category_count": len(category_counts),
        "category_labels": sorted(category_counts),
        "category_training_counts": dict(sorted(category_counts.items())),
        "subcategory_labels": {
            category_id: sorted(counts) for category_id, counts in subcategory_counts.items()
        },
        "subcategory_training_counts": subcategory_counts,
        "subcategory_model_count": len(subcategory_models),
        "subcategory_constant_count": len(subcategory_constants),
        "subcategory_unresolved_categories": unresolved_categories,
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
            "minimum_subcategory_class_rows": MIN_SUBCATEGORY_CLASS_ROWS,
            "direction_feature": "signed_amount",
            "kind_feature": "transaction_kind",
        },
    }
    artifact = {
        "metadata": metadata,
        "category_model": category_model,
        "subcategory_models": subcategory_models,
        "subcategory_constants": subcategory_constants,
    }

    checksum = _activate_artifact(
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
        category_count=len(category_counts),
        subcategory_model_count=len(subcategory_models),
        subcategory_constant_count=len(subcategory_constants),
        checksum=checksum,
        sklearn_version=sklearn.__version__,
        taxonomy_version=taxonomy.version,
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


def _activate_artifact(
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
        session.execute(
            update(ModelVersion).where(ModelVersion.is_active.is_(True)).values(is_active=False)
        )
        session.add(
            ModelVersion(
                id=model_version_id,
                name=model_name,
                artifact_path=artifact_path.relative_to(resolved_data_dir).as_posix(),
                checksum=checksum,
                training_metadata=metadata,
                taxonomy_version=str(metadata["taxonomy_version"]),
                is_active=True,
                created_at=created_at,
                activated_at=created_at,
            )
        )
        session.commit()
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
