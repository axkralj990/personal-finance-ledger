from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from backend.app.api.dependencies import SessionDependency
from backend.app.database.models import Category, Subcategory, utc_now
from backend.app.problems import Problem
from backend.app.taxonomy.seed import taxonomy_slug

router = APIRouter(prefix="/categories", tags=["taxonomy"])


class SubcategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    category_id: str
    slug: str
    display_name: str
    sort_order: int
    is_active: bool


class CategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    slug: str
    display_name: str
    sort_order: int
    is_active: bool
    subcategories: list[SubcategoryRead]


class TaxonomyCreate(BaseModel):
    display_name: str = Field(min_length=1, max_length=120)
    parent_category_id: str | None = None
    sort_order: int = 0
    is_active: bool = True


class TaxonomyPatch(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=120)
    sort_order: int | None = None
    is_active: bool | None = None


@router.get("", response_model=list[CategoryRead])
def list_categories(session: SessionDependency) -> list[Category]:
    query = select(Category).order_by(Category.sort_order, Category.display_name)
    return list(session.scalars(query))


@router.post("", response_model=CategoryRead | SubcategoryRead, status_code=201)
def create_taxonomy_item(
    payload: TaxonomyCreate, session: SessionDependency
) -> Category | Subcategory:
    slug = taxonomy_slug(payload.display_name)
    if payload.parent_category_id:
        parent = session.get(Category, payload.parent_category_id)
        if parent is None:
            raise Problem(404, "category_not_found", "Parent category was not found")
        exists = session.scalar(
            select(Subcategory).where(
                Subcategory.category_id == parent.id, Subcategory.slug == slug
            )
        )
        if exists:
            raise Problem(409, "subcategory_exists", "Subcategory already exists")
        item: Category | Subcategory = Subcategory(
            category_id=parent.id,
            slug=slug,
            display_name=payload.display_name,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
    else:
        if session.scalar(select(Category).where(Category.slug == slug)):
            raise Problem(409, "category_exists", "Category already exists")
        item = Category(
            slug=slug,
            display_name=payload.display_name,
            sort_order=payload.sort_order,
            is_active=payload.is_active,
        )
    session.add(item)
    session.commit()
    return item


@router.patch("/{item_id}", response_model=CategoryRead | SubcategoryRead)
def patch_taxonomy_item(
    item_id: str, payload: TaxonomyPatch, session: SessionDependency
) -> Category | Subcategory:
    item: Category | Subcategory | None = session.get(Category, item_id)
    if item is None:
        item = session.get(Subcategory, item_id)
    if item is None:
        raise Problem(404, "taxonomy_item_not_found", "Taxonomy item was not found")
    values = payload.model_dump(exclude_unset=True)
    if values.get("display_name"):
        values["slug"] = taxonomy_slug(values["display_name"])
    for key, value in values.items():
        setattr(item, key, value)
    item.updated_at = utc_now()
    session.commit()
    return item
