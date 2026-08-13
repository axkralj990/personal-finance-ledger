from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import case, or_, select
from sqlalchemy.orm import Session

from backend.app.database.models import (
    Account,
    Category,
    ModelVersion,
    RuleScope,
    StagedTransaction,
    Subcategory,
    TagRule,
)
from backend.app.tagging.model import (
    InferenceModel,
    TaxonomySnapshot,
    current_taxonomy,
    load_inference_model,
)


@dataclass(frozen=True, slots=True)
class TaggingContext:
    model: InferenceModel | None
    taxonomy: TaxonomySnapshot


def prepare_tagging(session: Session, data_dir: Path) -> TaggingContext:
    active_model = session.scalar(
        select(ModelVersion).where(ModelVersion.is_active.is_(True)).limit(1)
    )
    return TaggingContext(
        model=load_inference_model(active_model, data_dir),
        taxonomy=current_taxonomy(session),
    )


def apply_tagging(
    session: Session,
    staged: StagedTransaction,
    account: Account,
    context: TaggingContext | None = None,
) -> None:
    rule = session.scalar(
        select(TagRule)
        .join(Category, Category.id == TagRule.category_id)
        .outerjoin(Subcategory, Subcategory.id == TagRule.subcategory_id)
        .where(
            TagRule.is_enabled.is_(True),
            Category.is_active.is_(True),
            or_(TagRule.subcategory_id.is_(None), Subcategory.is_active.is_(True)),
            TagRule.normalized_description == staged.normalized_description,
            (
                (TagRule.scope == RuleScope.ACCOUNT) & (TagRule.account_id == account.id)
                | (TagRule.scope == RuleScope.GLOBAL)
            ),
        )
        .order_by(
            case(
                (TagRule.scope == RuleScope.ACCOUNT, 1),
                else_=2,
            ),
            TagRule.created_at.desc(),
        )
    )
    if rule:
        staged.predicted_category_id = rule.category_id
        staged.predicted_subcategory_id = rule.subcategory_id
        staged.prediction_confidence = 1.0
        staged.category_id = rule.category_id
        staged.subcategory_id = rule.subcategory_id
        return

    if context is None:
        raise ValueError("tagging context is required when no active rule matches")
    if (
        context.model is None
        or staged.description is None
        or staged.amount_minor is None
        or staged.kind is None
    ):
        return
    try:
        prediction = context.model.predict(staged.description, staged.amount_minor, staged.kind)
    except Exception:
        return
    if prediction is None or prediction.category_id not in context.taxonomy.category_ids:
        return

    subcategory_id = prediction.subcategory_id
    subcategory_is_valid = subcategory_id is None or (
        context.taxonomy.subcategory_parents.get(subcategory_id) == prediction.category_id
    )
    staged.predicted_category_id = prediction.category_id
    staged.predicted_subcategory_id = subcategory_id if subcategory_is_valid else None
    staged.prediction_confidence = (
        prediction.confidence if subcategory_is_valid else prediction.category_confidence
    )
    staged.model_version_id = prediction.model_version_id

    taxonomy_is_current = prediction.taxonomy_checksum == context.taxonomy.checksum
    if prediction.auto_accept and taxonomy_is_current and subcategory_is_valid:
        staged.category_id = prediction.category_id
        staged.subcategory_id = subcategory_id


def validate_rule_scope(scope: RuleScope, account_id: str | None) -> None:
    valid = (scope == RuleScope.GLOBAL and account_id is None) or (
        scope == RuleScope.ACCOUNT and account_id is not None
    )
    if not valid:
        raise ValueError("scope fields do not match rule scope")
