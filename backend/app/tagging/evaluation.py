from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

from sklearn.model_selection import StratifiedGroupKFold

from backend.app.database.models import TransactionKind
from backend.app.tagging.model import JoblibInferenceModel, model_feature

MIN_SUBCATEGORY_CLASS_ROWS = 2
RANDOM_STATE = 42


@dataclass(frozen=True, slots=True)
class TrainingExample:
    normalized_description: str
    amount_minor: int
    kind: TransactionKind
    category_id: str
    subcategory_id: str | None

    @property
    def feature(self) -> str:
        return model_feature(self.normalized_description, self.amount_minor, self.kind)


@dataclass(frozen=True, slots=True)
class FittedHierarchy:
    category_model: Any
    subcategory_models: dict[str, Any]
    subcategory_constants: dict[str, str]
    category_counts: dict[str, int]
    subcategory_counts: dict[str, dict[str, int]]
    unresolved_categories: list[str]


@dataclass(frozen=True, slots=True)
class CrossValidationMetrics:
    requested_folds: int
    effective_folds: int
    evaluated_row_count: int
    category_accuracy: float
    exact_match_accuracy: float
    auto_accept_coverage: float
    auto_accept_accuracy: float | None

    def as_dict(self) -> dict[str, int | float | None]:
        return {
            "requested_folds": self.requested_folds,
            "effective_folds": self.effective_folds,
            "evaluated_row_count": self.evaluated_row_count,
            "category_accuracy": self.category_accuracy,
            "exact_match_accuracy": self.exact_match_accuracy,
            "auto_accept_coverage": self.auto_accept_coverage,
            "auto_accept_accuracy": self.auto_accept_accuracy,
        }


def fit_hierarchy(
    examples: Sequence[TrainingExample], classifier_factory: Callable[[], Any]
) -> FittedHierarchy:
    category_labels = [example.category_id for example in examples]
    category_counts = Counter(category_labels)
    if len(category_counts) < 2:
        raise ValueError("at least two category classes are required for training")

    category_model = classifier_factory().fit(
        [example.feature for example in examples], category_labels
    )
    subcategory_rows: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for example in examples:
        if example.subcategory_id is not None:
            subcategory_rows[example.category_id].append(
                (example.feature, example.subcategory_id)
            )

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
            subcategory_models[category_id] = classifier_factory().fit(
                [feature for feature, _ in rows], [label for _, label in rows]
            )
        else:
            unresolved_categories.append(category_id)

    return FittedHierarchy(
        category_model=category_model,
        subcategory_models=subcategory_models,
        subcategory_constants=subcategory_constants,
        category_counts=dict(sorted(category_counts.items())),
        subcategory_counts=subcategory_counts,
        unresolved_categories=unresolved_categories,
    )


def cross_validate_hierarchy(
    examples: Sequence[TrainingExample],
    classifier_factory: Callable[[], Any],
    *,
    requested_folds: int,
    category_threshold: float,
    subcategory_threshold: float,
) -> CrossValidationMetrics:
    groups = [example.normalized_description for example in examples]
    groups_by_category: dict[str, set[str]] = defaultdict(set)
    for example in examples:
        groups_by_category[example.category_id].add(example.normalized_description)

    effective_folds = min(
        requested_folds,
        len(set(groups)),
        *(len(category_groups) for category_groups in groups_by_category.values()),
    )
    if effective_folds < 2:
        raise ValueError(
            "at least two distinct description groups per category are required "
            "for cross-validation"
        )

    splitter = StratifiedGroupKFold(
        n_splits=effective_folds,
        shuffle=True,
        random_state=RANDOM_STATE,
    )
    labels = [example.category_id for example in examples]
    category_correct = 0
    exact_match_correct = 0
    auto_accepted = 0
    auto_accepted_correct = 0

    for train_indices, test_indices in splitter.split(examples, labels, groups):
        hierarchy = fit_hierarchy([examples[index] for index in train_indices], classifier_factory)
        inference = JoblibInferenceModel(
            model_version_id="cross-validation",
            taxonomy_checksum="cross-validation",
            category_threshold=category_threshold,
            subcategory_threshold=subcategory_threshold,
            category_model=hierarchy.category_model,
            subcategory_models=hierarchy.subcategory_models,
            subcategory_constants=hierarchy.subcategory_constants,
        )
        for index in test_indices:
            example = examples[index]
            prediction = inference.predict(
                example.normalized_description,
                example.amount_minor,
                example.kind,
            )
            if prediction is None:
                continue
            category_matches = prediction.category_id == example.category_id
            exact_matches = (
                category_matches and prediction.subcategory_id == example.subcategory_id
            )
            category_correct += int(category_matches)
            exact_match_correct += int(exact_matches)
            if prediction.auto_accept:
                auto_accepted += 1
                auto_accepted_correct += int(exact_matches)

    evaluated = len(examples)
    return CrossValidationMetrics(
        requested_folds=requested_folds,
        effective_folds=effective_folds,
        evaluated_row_count=evaluated,
        category_accuracy=category_correct / evaluated,
        exact_match_accuracy=exact_match_correct / evaluated,
        auto_accept_coverage=auto_accepted / evaluated,
        auto_accept_accuracy=(auto_accepted_correct / auto_accepted if auto_accepted else None),
    )
