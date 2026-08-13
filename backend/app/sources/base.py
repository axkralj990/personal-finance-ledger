from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from backend.app.database.models import StagedDisposition, TransactionKind


@dataclass(slots=True)
class ParsedRow:
    row_number: int
    raw: dict[str, Any]
    transaction_date: date | None
    transaction_at: datetime | None
    description: str | None
    amount_minor: int | None
    currency: str | None
    kind: TransactionKind | None
    source_native_id: str | None = None
    disposition: StagedDisposition = StagedDisposition.PENDING
    ignore_reason: str | None = None
    issues: list[dict[str, Any]] = field(default_factory=list)
    category_id: str | None = None
    subcategory_id: str | None = None
