from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select

from backend.app.api.dependencies import SessionDependency
from backend.app.api.pagination import Page
from backend.app.database.models import Provider, RuleScope, TagRule, utc_now
from backend.app.problems import Problem
from backend.app.sources.normalization import normalize_description
from backend.app.tagging.service import validate_rule_scope
from backend.app.taxonomy.validation import validate_active_taxonomy

router = APIRouter(prefix="/tag-rules", tags=["tag rules"])


class TagRuleCreate(BaseModel):
    description: str = Field(min_length=1)
    scope: RuleScope
    source_account_id: str | None = None
    provider: Provider | None = None
    category_id: str
    subcategory_id: str | None = None


class TagRulePatch(BaseModel):
    is_enabled: bool | None = None
    category_id: str | None = None
    subcategory_id: str | None = None


class TagRuleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    normalized_description: str
    scope: RuleScope
    source_account_id: str | None
    provider: Provider | None
    category_id: str
    subcategory_id: str | None
    is_enabled: bool


@router.get("", response_model=Page[TagRuleRead])
def list_tag_rules(
    session: SessionDependency,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
) -> Page[TagRuleRead]:
    total = int(session.scalar(select(func.count()).select_from(TagRule)) or 0)
    items = list(
        session.scalars(
            select(TagRule)
            .order_by(TagRule.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    )
    return Page(items=items, page=page, page_size=page_size, total=total)


@router.post("", response_model=TagRuleRead, status_code=201)
def create_tag_rule(payload: TagRuleCreate, session: SessionDependency) -> TagRule:
    try:
        validate_rule_scope(payload.scope, payload.source_account_id, payload.provider)
    except ValueError as exc:
        raise Problem(422, "invalid_rule_scope", str(exc), field="scope") from exc
    validate_active_taxonomy(session, payload.category_id, payload.subcategory_id)
    rule = TagRule(
        normalized_description=normalize_description(payload.description),
        **payload.model_dump(exclude={"description"}),
    )
    session.add(rule)
    session.commit()
    return rule


@router.patch("/{rule_id}", response_model=TagRuleRead)
def patch_tag_rule(rule_id: str, payload: TagRulePatch, session: SessionDependency) -> TagRule:
    rule = session.get(TagRule, rule_id)
    if rule is None:
        raise Problem(404, "tag_rule_not_found", "Tag rule was not found")
    values = payload.model_dump(exclude_unset=True)
    category_id = values.get("category_id", rule.category_id)
    subcategory_id = values.get("subcategory_id", rule.subcategory_id)
    validate_active_taxonomy(session, category_id, subcategory_id)
    for key, value in values.items():
        setattr(rule, key, value)
    rule.updated_at = utc_now()
    session.commit()
    return rule
