import re
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database.models import Category, Subcategory

TAXONOMY_NAMESPACE = uuid.UUID("a92ef020-b589-42a9-adfa-4c918241ca5b")

# This is the managed hierarchy observed in data/dashboard/transactions.csv on 2026-08-09.
OBSERVED_TAXONOMY: dict[str, tuple[str, ...]] = {
    "apartment": ("expenses", "ikea", "insurance", "kitchen", "machines", "misc", "plants", "tech"),
    "app": ("ai", "entertainment", "health", "misc", "music", "storage"),
    "food": ("alcohol", "groceries", "out", "reimbursed", "wolt"),
    "health": ("contacts", "cosmetics", "misc", "pharmacy", "spa", "supplements", "test"),
    "income": (
        "FF",
        "FirstClass",
        "Neurotherapeutix",
        "Pareto",
        "Polipop",
        "aformx",
        "flying",
        "misc",
        "oldstuFF",
        "rent",
    ),
    "lifestyle": (
        "books",
        "clothes",
        "cosmetics",
        "entertainment",
        "fragrance",
        "hair",
        "misc",
        "tech",
        "tuition",
    ),
    "misc": ("bank", "documents", "gift", "insurance", "misc"),
    "sport": ("bike", "bjj", "climbing", "flying", "misc", "swimming"),
    "transport": ("bank", "car", "fine", "gas", "parking", "public", "tolls"),
    "travel": ("car", "hotel", "hotels", "misc", "plane", "total"),
    "work expenses": ("FF", "Neurotherapeutix", "Pareto", "Polipop", "SP", "misc", "taxes"),
}

TAXONOMY_ALIASES = {"msic": "misc"}


def taxonomy_slug(value: str) -> str:
    normalized = TAXONOMY_ALIASES.get(value.strip().casefold(), value.strip().casefold())
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def taxonomy_id(kind: str, *values: str) -> str:
    return str(uuid.uuid5(TAXONOMY_NAMESPACE, ":".join((kind, *values))))


def seed_taxonomy(session: Session) -> None:
    existing = set(session.scalars(select(Category.slug)))
    for category_order, (category_name, subcategory_names) in enumerate(OBSERVED_TAXONOMY.items()):
        category_slug = taxonomy_slug(category_name)
        category_id = taxonomy_id("category", category_slug)
        if category_slug not in existing:
            session.add(
                Category(
                    id=category_id,
                    slug=category_slug,
                    display_name=category_name,
                    sort_order=category_order,
                )
            )
        for subcategory_order, subcategory_name in enumerate(subcategory_names):
            subcategory_slug = taxonomy_slug(subcategory_name)
            subcategory_id = taxonomy_id("subcategory", category_slug, subcategory_slug)
            if session.get(Subcategory, subcategory_id) is None:
                session.add(
                    Subcategory(
                        id=subcategory_id,
                        category_id=category_id,
                        slug=subcategory_slug,
                        display_name=subcategory_name,
                        sort_order=subcategory_order,
                    )
                )
    session.flush()


def resolve_taxonomy(
    session: Session, category_value: str, subcategory_value: str | None
) -> tuple[str | None, str | None]:
    category_slug = taxonomy_slug(category_value)
    category = session.scalar(select(Category).where(Category.slug == category_slug))
    if category is None:
        return None, None
    if not subcategory_value or not subcategory_value.strip():
        return category.id, None
    subcategory_slug = taxonomy_slug(subcategory_value)
    subcategory = session.scalar(
        select(Subcategory).where(
            Subcategory.category_id == category.id,
            Subcategory.slug == subcategory_slug,
        )
    )
    return category.id, subcategory.id if subcategory else None
