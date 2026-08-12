from sqlalchemy.orm import Session

from backend.app.database.models import Category, Subcategory
from backend.app.problems import Problem


def validate_active_taxonomy(
    session: Session,
    category_id: str | None,
    subcategory_id: str | None,
    *,
    row: int | None = None,
) -> None:
    if category_id is None:
        if subcategory_id is not None:
            raise Problem(
                422,
                "taxonomy_parent_mismatch",
                "A subcategory requires a parent category",
                field="subcategory_id",
                row=row,
                recoverable=True,
            )
        return

    category = session.get(Category, category_id)
    if category is None or not category.is_active:
        raise Problem(
            422,
            "category_not_found",
            "Active category was not found",
            field="category_id",
            row=row,
            recoverable=True,
        )
    if subcategory_id is None:
        return

    subcategory = session.get(Subcategory, subcategory_id)
    if subcategory is None or not subcategory.is_active or subcategory.category_id != category.id:
        raise Problem(
            422,
            "taxonomy_parent_mismatch",
            "Active subcategory does not belong to the selected category",
            field="subcategory_id",
            row=row,
            recoverable=True,
        )
