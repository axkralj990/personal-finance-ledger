import hashlib
import io
import json
import logging
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import joblib
import sklearn
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database.models import (
    Category,
    ModelVersion,
    Subcategory,
    TransactionKind,
)
from backend.app.sources.normalization import normalize_description

ARTIFACT_SCHEMA_VERSION = 1
TAXONOMY_VERSION = "active-taxonomy-v1"
logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class TagPrediction:
    category_id: str
    subcategory_id: str | None
    confidence: float
    category_confidence: float
    subcategory_confidence: float | None
    model_version_id: str
    taxonomy_checksum: str
    auto_accept: bool


@dataclass(frozen=True, slots=True)
class TaxonomySnapshot:
    category_ids: frozenset[str]
    subcategory_parents: dict[str, str]
    checksum: str
    version: str = TAXONOMY_VERSION


class InferenceModel(Protocol):
    def predict(
        self, description: str, amount_minor: int, kind: TransactionKind
    ) -> TagPrediction | None: ...


@dataclass(frozen=True, slots=True)
class JoblibInferenceModel:
    model_version_id: str
    taxonomy_checksum: str
    category_threshold: float
    subcategory_threshold: float
    category_model: Any
    subcategory_models: dict[str, Any]
    subcategory_constants: dict[str, str]

    def predict(
        self, description: str, amount_minor: int, kind: TransactionKind
    ) -> TagPrediction | None:
        feature = model_feature(description, amount_minor, kind)
        category_id, category_confidence = _highest_probability(self.category_model, feature)
        subcategory_id: str | None = None
        subcategory_confidence: float | None = None
        has_subcategory_strategy = False

        subcategory_model = self.subcategory_models.get(category_id)
        if subcategory_model is not None:
            has_subcategory_strategy = True
            subcategory_id, subcategory_confidence = _highest_probability(
                subcategory_model, feature
            )
        elif category_id in self.subcategory_constants:
            has_subcategory_strategy = True
            subcategory_id = self.subcategory_constants[category_id]
            subcategory_confidence = 1.0

        confidence = category_confidence
        auto_accept = has_subcategory_strategy and category_confidence >= self.category_threshold
        if subcategory_confidence is not None:
            confidence *= subcategory_confidence
            auto_accept = auto_accept and subcategory_confidence >= self.subcategory_threshold

        return TagPrediction(
            category_id=category_id,
            subcategory_id=subcategory_id,
            confidence=confidence,
            category_confidence=category_confidence,
            subcategory_confidence=subcategory_confidence,
            model_version_id=self.model_version_id,
            taxonomy_checksum=self.taxonomy_checksum,
            auto_accept=auto_accept,
        )


def model_feature(description: str, amount_minor: int, kind: TransactionKind) -> str:
    normalized = normalize_description(description)
    direction = "credit" if amount_minor > 0 else "debit" if amount_minor < 0 else "zero"
    amount_kind = "income" if amount_minor > 0 else "expense"
    return f"{normalized} __kind_{amount_kind} __direction_{direction}"


def current_taxonomy(session: Session) -> TaxonomySnapshot:
    categories = list(
        session.execute(
            select(Category.id, Category.slug)
            .where(Category.is_active.is_(True))
            .order_by(Category.id)
        )
    )
    subcategories = list(
        session.execute(
            select(Subcategory.id, Subcategory.category_id, Subcategory.slug)
            .join(Category, Category.id == Subcategory.category_id)
            .where(Subcategory.is_active.is_(True), Category.is_active.is_(True))
            .order_by(Subcategory.id)
        )
    )
    payload = {
        "categories": [{"id": category_id, "slug": slug} for category_id, slug in categories],
        "subcategories": [
            {"id": subcategory_id, "category_id": category_id, "slug": slug}
            for subcategory_id, category_id, slug in subcategories
        ],
        "version": TAXONOMY_VERSION,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return TaxonomySnapshot(
        category_ids=frozenset(category_id for category_id, _ in categories),
        subcategory_parents={
            subcategory_id: category_id for subcategory_id, category_id, _ in subcategories
        },
        checksum=hashlib.sha256(encoded).hexdigest(),
    )


def load_inference_model(metadata: ModelVersion | None, data_dir: Path) -> InferenceModel | None:
    if metadata is None or not metadata.is_active:
        return None
    relative_path = Path(metadata.artifact_path)
    base_path = data_dir.resolve()
    if relative_path.is_absolute():
        logger.warning("Active model %s unavailable: invalid artifact path", metadata.id)
        return None
    artifact = (base_path / relative_path).resolve()
    if not artifact.is_relative_to(base_path):
        logger.warning("Active model %s unavailable: invalid artifact path", metadata.id)
        return None
    if not artifact.is_file():
        logger.warning("Active model %s unavailable: artifact is missing", metadata.id)
        return None
    try:
        return verify_model_artifact(
            artifact,
            metadata.checksum,
            metadata.id,
            metadata.taxonomy_version,
            metadata.training_metadata,
        )
    except Exception as exc:
        logger.warning(
            "Active model %s unavailable: verification failed (%s)",
            metadata.id,
            type(exc).__name__,
        )
        return None


def verify_model_artifact(
    artifact_path: Path,
    checksum: str,
    model_version_id: str,
    taxonomy_version: str,
    training_metadata: dict[str, Any],
) -> JoblibInferenceModel:
    return _load_verified_model(
        str(artifact_path.resolve()),
        checksum,
        model_version_id,
        taxonomy_version,
        _json_digest(training_metadata),
    )


@lru_cache(maxsize=8)
def _load_verified_model(
    artifact_path: str,
    checksum: str,
    model_version_id: str,
    taxonomy_version: str,
    metadata_digest: str,
) -> JoblibInferenceModel:
    artifact_bytes = Path(artifact_path).read_bytes()
    if hashlib.sha256(artifact_bytes).hexdigest() != checksum:
        raise ValueError("model artifact checksum mismatch")

    # joblib artifacts are executable pickle data. The hash is checked before loading,
    # and deployment documentation restricts artifacts to trusted local backups/training.
    artifact = joblib.load(io.BytesIO(artifact_bytes))
    if not isinstance(artifact, dict):
        raise TypeError("invalid model artifact")
    artifact_metadata = artifact.get("metadata")
    if not isinstance(artifact_metadata, dict):
        raise TypeError("model artifact metadata is missing")
    if artifact_metadata.get("artifact_schema_version") != ARTIFACT_SCHEMA_VERSION:
        raise ValueError("incompatible model artifact schema")
    if artifact_metadata.get("model_version_id") != model_version_id:
        raise ValueError("model artifact version mismatch")
    if artifact_metadata.get("taxonomy_version") != taxonomy_version:
        raise ValueError("model artifact taxonomy version mismatch")
    if artifact_metadata.get("library_versions", {}).get("scikit_learn") != sklearn.__version__:
        raise ValueError("model artifact scikit-learn version mismatch")
    if _json_digest(artifact_metadata) != metadata_digest:
        raise ValueError("model artifact metadata mismatch")

    thresholds = artifact_metadata.get("thresholds", {})
    category_model = artifact.get("category_model")
    subcategory_models = artifact.get("subcategory_models")
    subcategory_constants = artifact.get("subcategory_constants")
    if (
        category_model is None
        or not isinstance(subcategory_models, dict)
        or not isinstance(subcategory_constants, dict)
    ):
        raise ValueError("model artifact estimators are missing")
    return JoblibInferenceModel(
        model_version_id=model_version_id,
        taxonomy_checksum=str(artifact_metadata["taxonomy_checksum"]),
        category_threshold=float(thresholds["category"]),
        subcategory_threshold=float(thresholds["subcategory"]),
        category_model=category_model,
        subcategory_models=subcategory_models,
        subcategory_constants=subcategory_constants,
    )


def _highest_probability(estimator: Any, feature: str) -> tuple[str, float]:
    probabilities = estimator.predict_proba([feature])[0]
    index = int(probabilities.argmax())
    return str(estimator.classes_[index]), float(probabilities[index])


def _json_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()
