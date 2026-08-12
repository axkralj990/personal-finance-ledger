"""Initial personal finance schema and managed taxonomy."""

import re
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20260809_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TAXONOMY_NAMESPACE = uuid.UUID("a92ef020-b589-42a9-adfa-4c918241ca5b")
SOURCE_ACCOUNT_NAMESPACE = uuid.UUID("8927873d-f129-49d6-bbd4-e400552a471b")

SOURCE_ACCOUNTS = (
    ("LEGACY", "Legacy historical ledger", "EUR"),
    ("REVOLUT", "Revolut Personal EUR", "EUR"),
    ("REVOLUT", "Revolut Joint EUR", "EUR"),
    ("DBS", "DBS EUR", "EUR"),
    ("MASTERCARD", "Mastercard EUR", "EUR"),
    ("MANUAL", "Manual EUR", "EUR"),
)

OBSERVED_TAXONOMY = {
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


def upgrade() -> None:
    op.create_table(
        "source_accounts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "provider",
            sa.Enum(
                "LEGACY",
                "REVOLUT",
                "DBS",
                "MASTERCARD",
                "MANUAL",
                name="provider",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(120), nullable=False, unique=True),
        sa.Column("default_currency", sa.String(3), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("length(default_currency) = 3"),
    )
    op.create_index("ix_source_accounts_provider", "source_accounts", ["provider"])

    op.create_table(
        "categories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("slug", sa.String(100), nullable=False, unique=True),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "subcategories",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "category_id",
            sa.String(36),
            sa.ForeignKey("categories.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("display_name", sa.String(120), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("category_id", "slug"),
        sa.UniqueConstraint("id", "category_id"),
    )
    op.create_table(
        "import_batches",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_account_id",
            sa.String(36),
            sa.ForeignKey("source_accounts.id"),
            nullable=False,
        ),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("retained_path", sa.String(1024)),
        sa.Column("file_sha256", sa.String(64), nullable=False),
        sa.Column("parser_version", sa.String(40), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "UPLOADED",
                "PARSED",
                "NEEDS_REVIEW",
                "READY",
                "COMMITTED",
                "FAILED",
                "DELETED",
                name="batchstatus",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("total_rows", sa.Integer(), nullable=False),
        sa.Column("included_rows", sa.Integer(), nullable=False),
        sa.Column("ignored_rows", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "uq_import_batch_file_active",
        "import_batches",
        ["source_account_id", "file_sha256"],
        unique=True,
        sqlite_where=sa.text("status != 'DELETED'"),
    )
    op.create_index("ix_import_batches_source_account_id", "import_batches", ["source_account_id"])
    op.create_index("ix_import_batches_status", "import_batches", ["status"])

    op.create_table(
        "model_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False, unique=True),
        sa.Column("artifact_path", sa.String(1024), nullable=False),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("training_metadata", sa.JSON(), nullable=False),
        sa.Column("taxonomy_version", sa.String(64), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("activated_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "uq_one_active_model",
        "model_versions",
        ["is_active"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
    )

    op.create_table(
        "staged_transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("import_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "ledger_account_id",
            sa.String(36),
            sa.ForeignKey("source_accounts.id"),
            nullable=False,
        ),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("raw_json", sa.JSON(), nullable=False),
        sa.Column("transaction_date", sa.Date()),
        sa.Column("transaction_at", sa.DateTime(timezone=True)),
        sa.Column("description", sa.Text()),
        sa.Column("normalized_description", sa.Text()),
        sa.Column("amount_minor", sa.Integer()),
        sa.Column("currency", sa.String(3)),
        sa.Column(
            "kind",
            sa.Enum(
                "EXPENSE",
                "INCOME",
                "REFUND",
                "FEE",
                "TRANSFER",
                name="transactionkind",
                native_enum=False,
                create_constraint=True,
            ),
        ),
        sa.Column("source_native_id", sa.String(255)),
        sa.Column("row_fingerprint", sa.String(64)),
        sa.Column("predicted_category_id", sa.String(36), sa.ForeignKey("categories.id")),
        sa.Column("predicted_subcategory_id", sa.String(36), sa.ForeignKey("subcategories.id")),
        sa.Column("prediction_confidence", sa.Float()),
        sa.Column("model_version_id", sa.String(36), sa.ForeignKey("model_versions.id")),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id")),
        sa.Column("subcategory_id", sa.String(36), sa.ForeignKey("subcategories.id")),
        sa.Column("validation_issues", sa.JSON(), nullable=False),
        sa.Column(
            "duplicate_status",
            sa.Enum(
                "NONE",
                "EXACT",
                "LIKELY",
                name="duplicatestatus",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("duplicate_candidate_id", sa.String(36), sa.ForeignKey("transactions.id")),
        sa.Column("duplicate_explanation", sa.Text()),
        sa.Column(
            "disposition",
            sa.Enum(
                "PENDING",
                "INCLUDE",
                "IGNORE",
                "BLOCKED",
                "AUDIT_ONLY",
                "COMMITTED",
                name="stageddisposition",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("ignore_reason", sa.Text()),
        sa.Column("remember_correction", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("batch_id", "row_number"),
        sa.CheckConstraint("subcategory_id IS NULL OR category_id IS NOT NULL"),
        sa.ForeignKeyConstraint(
            ["subcategory_id", "category_id"],
            ["subcategories.id", "subcategories.category_id"],
            name="fk_staged_taxonomy_parent",
        ),
    )
    op.create_index(
        "ix_staged_transactions_ledger_account_id", "staged_transactions", ["ledger_account_id"]
    )

    op.create_table(
        "transactions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "source_account_id",
            sa.String(36),
            sa.ForeignKey("source_accounts.id"),
            nullable=False,
        ),
        sa.Column("transaction_date", sa.Date(), nullable=False),
        sa.Column("transaction_at", sa.DateTime(timezone=True)),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("normalized_description", sa.Text(), nullable=False),
        sa.Column("amount_minor", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                "EXPENSE",
                "INCOME",
                "REFUND",
                "FEE",
                "TRANSFER",
                name="transactionkind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id")),
        sa.Column("subcategory_id", sa.String(36), sa.ForeignKey("subcategories.id")),
        sa.Column("source_native_id", sa.String(255)),
        sa.Column("row_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "import_batch_id", sa.String(36), sa.ForeignKey("import_batches.id"), nullable=False
        ),
        sa.Column(
            "staged_transaction_id",
            sa.String(36),
            sa.ForeignKey("staged_transactions.id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("is_excluded", sa.Boolean(), nullable=False),
        sa.Column("exclusion_reason", sa.Text()),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("corrected_at", sa.DateTime(timezone=True)),
        sa.Column("excluded_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("source_account_id", "row_fingerprint"),
        sa.CheckConstraint("length(currency) = 3"),
        sa.CheckConstraint("subcategory_id IS NULL OR category_id IS NOT NULL"),
        sa.ForeignKeyConstraint(
            ["subcategory_id", "category_id"],
            ["subcategories.id", "subcategories.category_id"],
            name="fk_transaction_taxonomy_parent",
        ),
    )
    op.create_index(
        "uq_transaction_native_id",
        "transactions",
        ["source_account_id", "source_native_id"],
        unique=True,
        sqlite_where=sa.text("source_native_id IS NOT NULL"),
    )
    for column in (
        "source_account_id",
        "transaction_date",
        "currency",
        "kind",
        "import_batch_id",
        "is_excluded",
    ):
        op.create_index(f"ix_transactions_{column}", "transactions", [column])

    op.create_table(
        "tag_rules",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("normalized_description", sa.Text(), nullable=False),
        sa.Column(
            "scope",
            sa.Enum(
                "GLOBAL",
                "PROVIDER",
                "ACCOUNT",
                name="rulescope",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("source_account_id", sa.String(36), sa.ForeignKey("source_accounts.id")),
        sa.Column(
            "provider",
            sa.Enum(
                "LEGACY",
                "REVOLUT",
                "DBS",
                "MASTERCARD",
                "MANUAL",
                name="provider",
                native_enum=False,
                create_constraint=True,
            ),
        ),
        sa.Column("category_id", sa.String(36), sa.ForeignKey("categories.id"), nullable=False),
        sa.Column("subcategory_id", sa.String(36), sa.ForeignKey("subcategories.id")),
        sa.Column("is_enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subcategory_id", "category_id"],
            ["subcategories.id", "subcategories.category_id"],
            name="fk_rule_taxonomy_parent",
        ),
        sa.CheckConstraint(
            "(scope = 'GLOBAL' AND source_account_id IS NULL AND provider IS NULL) OR "
            "(scope = 'PROVIDER' AND source_account_id IS NULL AND provider IS NOT NULL) OR "
            "(scope = 'ACCOUNT' AND source_account_id IS NOT NULL AND provider IS NULL)",
            name="ck_tag_rule_scope",
        ),
    )
    op.create_table(
        "transaction_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "transaction_id",
            sa.String(36),
            sa.ForeignKey("transactions.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(40), nullable=False),
        sa.Column("previous_values", sa.JSON(), nullable=False),
        sa.Column("new_values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    _seed_initial_data()


def downgrade() -> None:
    op.drop_table("transaction_events")
    op.drop_table("tag_rules")
    op.drop_table("transactions")
    op.drop_table("staged_transactions")
    op.drop_table("model_versions")
    op.drop_table("import_batches")
    op.drop_table("subcategories")
    op.drop_table("categories")
    op.drop_table("source_accounts")


def _seed_initial_data() -> None:
    now = datetime.now(UTC)
    source_table = sa.table(
        "source_accounts",
        sa.column("id", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("default_currency", sa.String()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )
    op.bulk_insert(
        source_table,
        [
            {
                "id": str(uuid.uuid5(SOURCE_ACCOUNT_NAMESPACE, display_name)),
                "provider": provider,
                "display_name": display_name,
                "default_currency": currency,
                "is_active": True,
                "created_at": now,
            }
            for provider, display_name, currency in SOURCE_ACCOUNTS
        ],
    )

    category_table = sa.table(
        "categories",
        sa.column("id", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    subcategory_table = sa.table(
        "subcategories",
        sa.column("id", sa.String()),
        sa.column("category_id", sa.String()),
        sa.column("slug", sa.String()),
        sa.column("display_name", sa.String()),
        sa.column("sort_order", sa.Integer()),
        sa.column("is_active", sa.Boolean()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    category_rows = []
    subcategory_rows = []
    for category_order, (category_name, subcategory_names) in enumerate(OBSERVED_TAXONOMY.items()):
        category_slug = _taxonomy_slug(category_name)
        category_id = _taxonomy_id("category", category_slug)
        category_rows.append(
            {
                "id": category_id,
                "slug": category_slug,
                "display_name": category_name,
                "sort_order": category_order,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
        )
        subcategory_rows.extend(
            {
                "id": _taxonomy_id("subcategory", category_slug, _taxonomy_slug(name)),
                "category_id": category_id,
                "slug": _taxonomy_slug(name),
                "display_name": name,
                "sort_order": subcategory_order,
                "is_active": True,
                "created_at": now,
                "updated_at": now,
            }
            for subcategory_order, name in enumerate(subcategory_names)
        )
    op.bulk_insert(category_table, category_rows)
    op.bulk_insert(subcategory_table, subcategory_rows)


def _taxonomy_slug(value: str) -> str:
    normalized = "misc" if value.strip().casefold() == "msic" else value.strip().casefold()
    return re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")


def _taxonomy_id(kind: str, *values: str) -> str:
    return str(uuid.uuid5(TAXONOMY_NAMESPACE, ":".join((kind, *values))))
