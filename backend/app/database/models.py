from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
    DDL,
    JSON,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    event,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from backend.app.currencies import ISO_CURRENCY_CODES


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class BatchStatus(enum.StrEnum):
    UPLOADED = "UPLOADED"
    AWAITING_MAPPING = "AWAITING_MAPPING"
    STAGING = "STAGING"
    PARSED = "PARSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY = "READY"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    DELETED = "DELETED"


class TransactionKind(enum.StrEnum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"


class DuplicateStatus(enum.StrEnum):
    NONE = "NONE"
    EXACT = "EXACT"
    LIKELY = "LIKELY"


class StagedDisposition(enum.StrEnum):
    PENDING = "PENDING"
    INCLUDE = "INCLUDE"
    IGNORE = "IGNORE"
    BLOCKED = "BLOCKED"
    AUDIT_ONLY = "AUDIT_ONLY"
    COMMITTED = "COMMITTED"


class RuleScope(enum.StrEnum):
    GLOBAL = "GLOBAL"
    ACCOUNT = "ACCOUNT"


class AssetType(enum.StrEnum):
    BANK_CASH = "BANK_CASH"
    BROKERAGE_CASH = "BROKERAGE_CASH"
    ETF = "ETF"
    STOCK = "STOCK"
    FIXED_ASSET = "FIXED_ASSET"
    OTHER = "OTHER"


class ValuationSource(enum.StrEnum):
    MANUAL = "MANUAL"
    TWELVE_DATA = "TWELVE_DATA"
    YAHOO_FINANCE = "YAHOO_FINANCE"


class QuoteInterval(enum.StrEnum):
    LIVE = "LIVE"
    MONTHLY = "MONTHLY"


class ImportExecutionPlanKind(enum.StrEnum):
    GUIDED_MAPPING = "GUIDED_MAPPING"
    ADAPTER_PROFILE = "ADAPTER_PROFILE"


class ImportMappingTemplateOrigin(enum.StrEnum):
    PREDEFINED = "PREDEFINED"
    LLM_CONFIRMED = "LLM_CONFIRMED"
    MANUAL = "MANUAL"


class ImportMappingSuggestionOutcome(enum.StrEnum):
    SUCCEEDED = "SUCCEEDED"
    AUTHENTICATION_ERROR = "AUTHENTICATION_ERROR"
    PERMISSION_ERROR = "PERMISSION_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    REFUSED = "REFUSED"
    PROVIDER_ERROR = "PROVIDER_ERROR"
    INVALID_OUTPUT = "INVALID_OUTPUT"
    STALE = "STALE"


enum_options = {"native_enum": False, "create_constraint": True, "validate_strings": True}


class Base(DeclarativeBase):
    pass


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    default_currency: Mapped[str] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        CheckConstraint(
            f"default_currency IN ({', '.join(repr(code) for code in sorted(ISO_CURRENCY_CODES))})",
            name="ck_accounts_default_currency",
        ),
    )


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    slug: Mapped[str] = mapped_column(String(100), unique=True)
    display_name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    subcategories: Mapped[list[Subcategory]] = relationship(
        back_populates="category", cascade="all, delete-orphan"
    )


class Subcategory(Base):
    __tablename__ = "subcategories"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id", ondelete="CASCADE"))
    slug: Mapped[str] = mapped_column(String(100))
    display_name: Mapped[str] = mapped_column(String(120))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    category: Mapped[Category] = relationship(back_populates="subcategories")

    __table_args__ = (
        UniqueConstraint("category_id", "slug"),
        UniqueConstraint("id", "category_id"),
    )


class ImportBatch(Base):
    __tablename__ = "import_batches"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    retained_path: Mapped[str | None] = mapped_column(String(1024))
    file_sha256: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[BatchStatus] = mapped_column(Enum(BatchStatus, **enum_options), index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1, server_default=text("1"))
    inspection_json: Mapped[dict[str, Any]] = mapped_column(
        JSON, default=dict, server_default=text("'{}'")
    )
    inspection_version: Mapped[str | None] = mapped_column(String(40))
    structural_signature: Mapped[str | None] = mapped_column(String(64))
    mapping_revision: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    current_mapping_origin: Mapped[ImportMappingTemplateOrigin | None] = mapped_column(
        Enum(ImportMappingTemplateOrigin, **enum_options)
    )
    current_profile_id: Mapped[str | None] = mapped_column(String(120))
    current_profile_version: Mapped[str | None] = mapped_column(String(40))
    current_provider: Mapped[str | None] = mapped_column(String(10))
    current_fingerprint_algorithm: Mapped[str | None] = mapped_column(String(80))
    current_fingerprint_version: Mapped[str | None] = mapped_column(String(40))
    current_mapping_diagnostics: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, server_default=text("'[]'")
    )
    source_mapping_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_mapping_templates.id", ondelete="RESTRICT")
    )
    source_mapping_template_version_id: Mapped[str | None] = mapped_column(String(36))
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    included_rows: Mapped[int] = mapped_column(Integer, default=0)
    ignored_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[Account] = relationship()
    staged_rows: Mapped[list[StagedTransaction]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    execution_plans: Mapped[list[ImportBatchExecutionPlan]] = relationship(
        back_populates="batch",
        order_by="ImportBatchExecutionPlan.mapping_revision",
    )
    suggestion_attempts: Mapped[list[ImportMappingSuggestionAttempt]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )
    source_mapping_template: Mapped[ImportMappingTemplate | None] = relationship(
        foreign_keys=[source_mapping_template_id]
    )
    source_mapping_template_version: Mapped[ImportMappingTemplateVersion | None] = relationship(
        foreign_keys=[source_mapping_template_version_id, source_mapping_template_id],
        overlaps="source_mapping_template",
    )

    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_import_batches_revision"),
        CheckConstraint("mapping_revision >= 0", name="ck_import_batches_mapping_revision"),
        CheckConstraint(
            "(current_mapping_origin IS NULL AND "
            "current_profile_id IS NULL AND current_profile_version IS NULL AND "
            "current_provider IS NULL AND current_fingerprint_algorithm IS NULL AND "
            "current_fingerprint_version IS NULL AND source_mapping_template_id IS NULL AND "
            "source_mapping_template_version_id IS NULL) OR "
            "(mapping_revision >= 1 AND current_mapping_origin IS NOT NULL AND "
            "current_fingerprint_algorithm IS NOT NULL AND "
            "current_fingerprint_version IS NOT NULL AND "
            "((current_profile_id IS NULL AND current_profile_version IS NULL AND "
            "current_provider IS NULL) OR (current_profile_id IS NOT NULL AND "
            "current_profile_version IS NOT NULL AND current_provider IS NOT NULL)))",
            name="ck_import_batches_current_mapping",
        ),
        CheckConstraint(
            "(source_mapping_template_id IS NULL AND "
            "source_mapping_template_version_id IS NULL) OR "
            "(source_mapping_template_id IS NOT NULL AND "
            "source_mapping_template_version_id IS NOT NULL)",
            name="ck_import_batches_source_template",
        ),
        ForeignKeyConstraint(
            ["source_mapping_template_version_id", "source_mapping_template_id"],
            [
                "import_mapping_template_versions.id",
                "import_mapping_template_versions.template_id",
            ],
            name="fk_import_batch_mapping_template_version",
            ondelete="RESTRICT",
        ),
        Index(
            "uq_import_batch_file_active",
            "account_id",
            "file_sha256",
            unique=True,
            sqlite_where=text("status != 'DELETED'"),
        ),
    )


class ImportMappingTemplate(Base):
    __tablename__ = "import_mapping_templates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120))
    structural_signature: Mapped[str] = mapped_column(String(64))
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id", ondelete="RESTRICT"))
    origin: Mapped[ImportMappingTemplateOrigin] = mapped_column(
        Enum(ImportMappingTemplateOrigin, **enum_options)
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    account: Mapped[Account | None] = relationship()
    versions: Mapped[list[ImportMappingTemplateVersion]] = relationship(
        back_populates="template",
        order_by="ImportMappingTemplateVersion.version",
    )

    __table_args__ = (
        CheckConstraint("revision >= 1", name="ck_import_mapping_templates_revision"),
        CheckConstraint(
            "origin != 'PREDEFINED' OR is_active = 1",
            name="ck_import_mapping_templates_predefined_active",
        ),
        Index(
            "ix_import_mapping_templates_match",
            "structural_signature",
            "account_id",
            "is_active",
        ),
        Index(
            "uq_import_mapping_templates_global_name",
            "name",
            unique=True,
            sqlite_where=text("account_id IS NULL"),
        ),
        Index(
            "uq_import_mapping_templates_account_name",
            "account_id",
            "name",
            unique=True,
            sqlite_where=text("account_id IS NOT NULL"),
        ),
    )


class ImportMappingTemplateVersion(Base):
    __tablename__ = "import_mapping_template_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    template_id: Mapped[str] = mapped_column(
        ForeignKey("import_mapping_templates.id", ondelete="CASCADE")
    )
    version: Mapped[int] = mapped_column(Integer)
    execution_plan_kind: Mapped[ImportExecutionPlanKind] = mapped_column(
        Enum(ImportExecutionPlanKind, **enum_options)
    )
    execution_plan_schema_version: Mapped[str] = mapped_column(String(40))
    execution_plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    template: Mapped[ImportMappingTemplate] = relationship(back_populates="versions")

    __table_args__ = (
        CheckConstraint("version >= 1", name="ck_import_mapping_template_versions_version"),
        UniqueConstraint("template_id", "version", name="uq_import_mapping_template_version"),
        UniqueConstraint("id", "template_id", name="uq_import_mapping_template_version_owner"),
    )


class ImportBatchExecutionPlan(Base):
    __tablename__ = "import_batch_execution_plans"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    mapping_revision: Mapped[int] = mapped_column(Integer)
    kind: Mapped[ImportExecutionPlanKind] = mapped_column(
        Enum(ImportExecutionPlanKind, **enum_options)
    )
    schema_version: Mapped[str] = mapped_column(String(40))
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    origin: Mapped[ImportMappingTemplateOrigin] = mapped_column(
        Enum(ImportMappingTemplateOrigin, **enum_options)
    )
    source_template_id: Mapped[str | None] = mapped_column(
        ForeignKey("import_mapping_templates.id", ondelete="RESTRICT")
    )
    source_template_version_id: Mapped[str | None] = mapped_column(String(36))
    profile_id: Mapped[str | None] = mapped_column(String(120))
    profile_version: Mapped[str | None] = mapped_column(String(40))
    provider: Mapped[str | None] = mapped_column(String(10))
    fingerprint_algorithm: Mapped[str] = mapped_column(String(80))
    fingerprint_version: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    batch: Mapped[ImportBatch] = relationship(back_populates="execution_plans")
    source_template: Mapped[ImportMappingTemplate | None] = relationship(
        foreign_keys=[source_template_id]
    )
    source_template_version: Mapped[ImportMappingTemplateVersion | None] = relationship(
        foreign_keys=[source_template_version_id, source_template_id],
        overlaps="source_template",
    )

    __table_args__ = (
        CheckConstraint("mapping_revision >= 1", name="ck_import_execution_plans_revision"),
        CheckConstraint(
            "(source_template_id IS NULL AND source_template_version_id IS NULL) OR "
            "(source_template_id IS NOT NULL AND source_template_version_id IS NOT NULL)",
            name="ck_import_execution_plans_source_template",
        ),
        CheckConstraint(
            "(kind = 'GUIDED_MAPPING' AND profile_id IS NULL AND "
            "profile_version IS NULL AND provider IS NULL) OR "
            "(kind = 'ADAPTER_PROFILE' AND profile_id IS NOT NULL AND "
            "profile_version IS NOT NULL AND provider IS NOT NULL)",
            name="ck_import_execution_plans_kind",
        ),
        ForeignKeyConstraint(
            ["source_template_version_id", "source_template_id"],
            ["import_mapping_template_versions.id", "import_mapping_template_versions.template_id"],
            name="fk_import_execution_plan_template_version",
            ondelete="RESTRICT",
        ),
        UniqueConstraint("batch_id", "mapping_revision", name="uq_import_batch_execution_plan"),
    )


class ImportMappingSuggestionAttempt(Base):
    __tablename__ = "import_mapping_suggestion_attempts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    batch_revision: Mapped[int] = mapped_column(Integer)
    attempt_number: Mapped[int] = mapped_column(Integer)
    model_name: Mapped[str] = mapped_column(String(120))
    provider_request_id: Mapped[str | None] = mapped_column(String(255))
    prompt_version: Mapped[str] = mapped_column(String(40))
    schema_version: Mapped[str] = mapped_column(String(40))
    payload_sha256: Mapped[str] = mapped_column(String(64))
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    duration_ms: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[ImportMappingSuggestionOutcome] = mapped_column(
        Enum(ImportMappingSuggestionOutcome, **enum_options)
    )
    execution_plan_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    error_class: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    batch: Mapped[ImportBatch] = relationship(back_populates="suggestion_attempts")

    __table_args__ = (
        CheckConstraint("batch_revision >= 1", name="ck_import_suggestions_batch_revision"),
        CheckConstraint("attempt_number >= 1", name="ck_import_suggestions_attempt_number"),
        CheckConstraint("duration_ms >= 0", name="ck_import_suggestions_duration"),
        CheckConstraint("length(payload_sha256) = 64", name="ck_import_suggestions_payload_sha256"),
        UniqueConstraint("batch_id", "attempt_number", name="uq_import_mapping_suggestion_attempt"),
        Index("ix_import_mapping_suggestions_batch_created", "batch_id", "created_at"),
    )


class StagedTransaction(Base):
    __tablename__ = "staged_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    transaction_date: Mapped[date | None] = mapped_column(Date)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str | None] = mapped_column(Text)
    normalized_description: Mapped[str | None] = mapped_column(Text)
    amount_minor: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(3))
    kind: Mapped[TransactionKind | None] = mapped_column(Enum(TransactionKind, **enum_options))
    source_native_id: Mapped[str | None] = mapped_column(String(255))
    row_fingerprint: Mapped[str | None] = mapped_column(String(64))
    predicted_category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    predicted_subcategory_id: Mapped[str | None] = mapped_column(ForeignKey("subcategories.id"))
    prediction_confidence: Mapped[float | None] = mapped_column(Float)
    model_version_id: Mapped[str | None] = mapped_column(ForeignKey("model_versions.id"))
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    subcategory_id: Mapped[str | None] = mapped_column(ForeignKey("subcategories.id"))
    validation_issues: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    duplicate_status: Mapped[DuplicateStatus] = mapped_column(
        Enum(DuplicateStatus, **enum_options), default=DuplicateStatus.NONE
    )
    duplicate_candidate_id: Mapped[str | None] = mapped_column(ForeignKey("transactions.id"))
    duplicate_explanation: Mapped[str | None] = mapped_column(Text)
    disposition: Mapped[StagedDisposition] = mapped_column(
        Enum(StagedDisposition, **enum_options), default=StagedDisposition.PENDING
    )
    ignore_reason: Mapped[str | None] = mapped_column(Text)
    remember_correction: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    batch: Mapped[ImportBatch] = relationship(back_populates="staged_rows")
    account: Mapped[Account] = relationship()

    __table_args__ = (
        UniqueConstraint("batch_id", "row_number"),
        CheckConstraint("subcategory_id IS NULL OR category_id IS NOT NULL"),
        ForeignKeyConstraint(
            ["subcategory_id", "category_id"],
            ["subcategories.id", "subcategories.category_id"],
            name="fk_staged_taxonomy_parent",
        ),
    )


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    account_id: Mapped[str] = mapped_column(ForeignKey("accounts.id"), index=True)
    transaction_date: Mapped[date] = mapped_column(Date, index=True)
    transaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    description: Mapped[str] = mapped_column(Text)
    normalized_description: Mapped[str] = mapped_column(Text)
    amount_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), index=True)
    kind: Mapped[TransactionKind] = mapped_column(Enum(TransactionKind, **enum_options), index=True)
    category_id: Mapped[str | None] = mapped_column(ForeignKey("categories.id"))
    subcategory_id: Mapped[str | None] = mapped_column(ForeignKey("subcategories.id"))
    source_native_id: Mapped[str | None] = mapped_column(String(255))
    row_fingerprint: Mapped[str] = mapped_column(String(64))
    import_batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id"), index=True)
    staged_transaction_id: Mapped[str] = mapped_column(
        ForeignKey("staged_transactions.id"), unique=True
    )
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    exclusion_reason: Mapped[str | None] = mapped_column(Text)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    corrected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[Account] = relationship()
    category: Mapped[Category | None] = relationship(foreign_keys=[category_id])
    subcategory: Mapped[Subcategory | None] = relationship(foreign_keys=[subcategory_id])

    __table_args__ = (
        UniqueConstraint("account_id", "row_fingerprint"),
        CheckConstraint("length(currency) = 3"),
        CheckConstraint(
            "(amount_minor > 0 AND kind = 'INCOME') OR (amount_minor < 0 AND kind = 'EXPENSE')",
            name="ck_transactions_amount_kind",
        ),
        CheckConstraint("subcategory_id IS NULL OR category_id IS NOT NULL"),
        ForeignKeyConstraint(
            ["subcategory_id", "category_id"],
            ["subcategories.id", "subcategories.category_id"],
            name="fk_transaction_taxonomy_parent",
        ),
        Index(
            "uq_transaction_native_id",
            "account_id",
            "source_native_id",
            unique=True,
            sqlite_where=text("source_native_id IS NOT NULL"),
        ),
    )


class TagRule(Base):
    __tablename__ = "tag_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    normalized_description: Mapped[str] = mapped_column(Text)
    scope: Mapped[RuleScope] = mapped_column(Enum(RuleScope, **enum_options))
    account_id: Mapped[str | None] = mapped_column(ForeignKey("accounts.id"))
    category_id: Mapped[str] = mapped_column(ForeignKey("categories.id"))
    subcategory_id: Mapped[str | None] = mapped_column(ForeignKey("subcategories.id"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (
        ForeignKeyConstraint(
            ["subcategory_id", "category_id"],
            ["subcategories.id", "subcategories.category_id"],
            name="fk_rule_taxonomy_parent",
        ),
        CheckConstraint(
            "(scope = 'GLOBAL' AND account_id IS NULL) OR "
            "(scope = 'ACCOUNT' AND account_id IS NOT NULL)",
            name="ck_tag_rule_scope",
        ),
    )


class ModelVersion(Base):
    __tablename__ = "model_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    artifact_path: Mapped[str] = mapped_column(String(1024))
    checksum: Mapped[str] = mapped_column(String(64))
    training_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    taxonomy_version: Mapped[str] = mapped_column(String(64))
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index(
            "uq_one_active_model",
            "is_active",
            unique=True,
            sqlite_where=text("is_active = 1"),
        ),
    )


class TransactionEvent(Base):
    __tablename__ = "transaction_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    transaction_id: Mapped[str] = mapped_column(ForeignKey("transactions.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(40))
    previous_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    new_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class TransactionDeletion(Base):
    __tablename__ = "transaction_deletions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    transaction_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(String(80), default="USER_DELETED")
    deleted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    name: Mapped[str] = mapped_column(String(160))
    asset_type: Mapped[AssetType] = mapped_column(Enum(AssetType, **enum_options), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    acquisition_date: Mapped[date] = mapped_column(Date)
    quantity: Mapped[str | None] = mapped_column(String(80))
    cost_basis_native_minor: Mapped[int | None] = mapped_column(Integer)
    cost_basis_eur_minor: Mapped[int | None] = mapped_column(Integer)
    cost_basis_fx_source: Mapped[str | None] = mapped_column(String(20))
    cost_basis_fx_rate_to_eur: Mapped[str | None] = mapped_column(String(80))
    cost_basis_fx_rate_date: Mapped[date | None] = mapped_column(Date)
    quote_symbol: Mapped[str | None] = mapped_column(String(40))
    quote_exchange: Mapped[str | None] = mapped_column(String(80))
    quote_mic_code: Mapped[str | None] = mapped_column(String(12))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_on: Mapped[date | None] = mapped_column(Date)

    valuations: Mapped[list[AssetValuation]] = relationship(back_populates="asset")
    events: Mapped[list[AssetEvent]] = relationship(back_populates="asset")

    __table_args__ = (
        CheckConstraint("length(currency) = 3", name="ck_assets_currency_length"),
        CheckConstraint("revision >= 1", name="ck_assets_revision"),
        CheckConstraint(
            "(cost_basis_native_minor IS NULL AND cost_basis_eur_minor IS NULL AND "
            "cost_basis_fx_source IS NULL AND cost_basis_fx_rate_to_eur IS NULL AND "
            "cost_basis_fx_rate_date IS NULL) OR "
            "(cost_basis_native_minor IS NOT NULL AND cost_basis_eur_minor IS NOT NULL AND "
            "cost_basis_fx_source IS NOT NULL AND cost_basis_fx_rate_to_eur IS NOT NULL AND "
            "cost_basis_fx_rate_date IS NOT NULL AND cost_basis_native_minor >= 0 AND "
            "cost_basis_eur_minor >= 0 AND cost_basis_native_minor <= 9007199254740991 AND "
            "cost_basis_eur_minor <= 9007199254740991)",
            name="ck_assets_cost_basis",
        ),
        CheckConstraint(
            "asset_type NOT IN ('BANK_CASH', 'BROKERAGE_CASH') OR "
            "(cost_basis_native_minor IS NULL AND cost_basis_eur_minor IS NULL)",
            name="ck_assets_cash_without_cost_basis",
        ),
        CheckConstraint(
            "(quote_symbol IS NULL AND quote_exchange IS NULL AND quote_mic_code IS NULL) OR "
            "(asset_type IN ('ETF', 'STOCK') AND quote_symbol IS NOT NULL AND "
            "(quote_exchange IS NOT NULL OR quote_mic_code IS NOT NULL))",
            name="ck_assets_quote_configuration",
        ),
        CheckConstraint(
            "(is_active = 1 AND archived_at IS NULL AND archived_on IS NULL) OR "
            "(is_active = 0 AND archived_at IS NOT NULL AND archived_on IS NOT NULL)",
            name="ck_assets_archive_state",
        ),
    )


class AssetValuation(Base):
    __tablename__ = "asset_valuations"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    valued_at: Mapped[date] = mapped_column(Date)
    native_value_minor: Mapped[int] = mapped_column(Integer)
    eur_value_minor: Mapped[int] = mapped_column(Integer)
    quantity: Mapped[str | None] = mapped_column(String(80))
    unit_price: Mapped[str | None] = mapped_column(String(80))
    cost_basis_native_minor: Mapped[int | None] = mapped_column(Integer)
    cost_basis_eur_minor: Mapped[int | None] = mapped_column(Integer)
    cost_basis_fx_source: Mapped[str | None] = mapped_column(String(20))
    cost_basis_fx_rate_to_eur: Mapped[str | None] = mapped_column(String(80))
    cost_basis_fx_rate_date: Mapped[date | None] = mapped_column(Date)
    source: Mapped[ValuationSource] = mapped_column(Enum(ValuationSource, **enum_options))
    quote_symbol: Mapped[str | None] = mapped_column(String(40))
    quote_exchange: Mapped[str | None] = mapped_column(String(80))
    quote_mic_code: Mapped[str | None] = mapped_column(String(12))
    quote_name: Mapped[str | None] = mapped_column(String(200))
    quote_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    quote_interval: Mapped[QuoteInterval | None] = mapped_column(
        Enum(QuoteInterval, **enum_options)
    )
    fx_source: Mapped[str] = mapped_column(String(20))
    fx_rate_to_eur: Mapped[str] = mapped_column(String(80))
    fx_rate_date: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    asset: Mapped[Asset] = relationship(back_populates="valuations")

    __table_args__ = (
        CheckConstraint(
            "native_value_minor BETWEEN 0 AND 9007199254740991",
            name="ck_asset_valuations_native_value",
        ),
        CheckConstraint(
            "eur_value_minor BETWEEN 0 AND 9007199254740991",
            name="ck_asset_valuations_eur_value",
        ),
        CheckConstraint("length(fx_rate_to_eur) > 0", name="ck_asset_valuations_fx_rate"),
        CheckConstraint(
            "(cost_basis_native_minor IS NULL AND cost_basis_eur_minor IS NULL AND "
            "cost_basis_fx_source IS NULL AND cost_basis_fx_rate_to_eur IS NULL AND "
            "cost_basis_fx_rate_date IS NULL) OR "
            "(cost_basis_native_minor IS NOT NULL AND cost_basis_eur_minor IS NOT NULL AND "
            "cost_basis_fx_source IS NOT NULL AND cost_basis_fx_rate_to_eur IS NOT NULL AND "
            "cost_basis_fx_rate_date IS NOT NULL AND cost_basis_native_minor >= 0 AND "
            "cost_basis_eur_minor >= 0 AND cost_basis_native_minor <= 9007199254740991 AND "
            "cost_basis_eur_minor <= 9007199254740991)",
            name="ck_asset_valuations_cost_basis",
        ),
        CheckConstraint(
            "(source = 'MANUAL' AND quote_symbol IS NULL AND quote_fetched_at IS NULL AND "
            "quote_interval IS NULL) OR "
            "(source IN ('TWELVE_DATA', 'YAHOO_FINANCE') AND quote_symbol IS NOT NULL AND "
            "quote_fetched_at IS NOT NULL AND quote_interval IS NOT NULL AND "
            "unit_price IS NOT NULL)",
            name="ck_asset_valuations_source_provenance",
        ),
        Index(
            "uq_asset_valuation_monthly",
            "asset_id",
            "source",
            "valued_at",
            unique=True,
            sqlite_where=text("quote_interval = 'MONTHLY'"),
        ),
        Index("ix_asset_valuations_asset_id_valued_at", "asset_id", "valued_at"),
        UniqueConstraint(
            "asset_id",
            "source",
            "quote_fetched_at",
            "valued_at",
            name="uq_asset_valuation_quote_replay",
        ),
    )


class AssetEvent(Base):
    __tablename__ = "asset_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="RESTRICT"))
    event_type: Mapped[str] = mapped_column(String(40))
    previous_revision: Mapped[int] = mapped_column(Integer)
    new_revision: Mapped[int] = mapped_column(Integer)
    effective_at: Mapped[date | None] = mapped_column(Date)
    previous_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    new_values: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    asset: Mapped[Asset] = relationship(back_populates="events")

    __table_args__ = (
        CheckConstraint("previous_revision >= 1", name="ck_asset_events_previous_revision"),
        CheckConstraint(
            "new_revision = previous_revision + 1", name="ck_asset_events_new_revision"
        ),
        Index("ix_asset_events_asset_id_created_at", "asset_id", "created_at"),
    )


_SQLITE_IMPORT_TRIGGERS = (
    "CREATE TRIGGER prevent_import_mapping_template_version_update "
    "BEFORE UPDATE ON import_mapping_template_versions "
    "BEGIN SELECT RAISE(ABORT, 'import mapping template versions are immutable'); END",
    "CREATE TRIGGER prevent_import_mapping_template_version_delete "
    "BEFORE DELETE ON import_mapping_template_versions "
    "BEGIN SELECT RAISE(ABORT, 'import mapping template versions are retained'); END",
    "CREATE TRIGGER prevent_import_batch_execution_plan_update "
    "BEFORE UPDATE ON import_batch_execution_plans "
    "BEGIN SELECT RAISE(ABORT, 'import batch execution plans are immutable'); END",
    "CREATE TRIGGER prevent_import_batch_execution_plan_delete "
    "BEFORE DELETE ON import_batch_execution_plans "
    "BEGIN SELECT RAISE(ABORT, 'import batch execution plans are retained'); END",
    "CREATE TRIGGER validate_import_batch_current_mapping_update "
    "BEFORE UPDATE OF mapping_revision, current_mapping_origin, current_profile_id, "
    "current_profile_version, current_provider, current_fingerprint_algorithm, "
    "current_fingerprint_version, source_mapping_template_id, "
    "source_mapping_template_version_id ON import_batches "
    "WHEN (NEW.mapping_revision >= 1 AND NOT EXISTS ("
    "SELECT 1 FROM import_batch_execution_plans AS plan "
    "WHERE plan.batch_id = NEW.id AND plan.mapping_revision = NEW.mapping_revision)) OR "
    "(NEW.current_mapping_origin IS NOT NULL AND EXISTS ("
    "SELECT 1 FROM import_batch_execution_plans AS plan "
    "WHERE plan.batch_id = NEW.id AND plan.mapping_revision = NEW.mapping_revision AND ("
    "plan.origin IS NOT NEW.current_mapping_origin OR "
    "plan.profile_id IS NOT NEW.current_profile_id OR "
    "plan.profile_version IS NOT NEW.current_profile_version OR "
    "plan.provider IS NOT NEW.current_provider OR "
    "plan.fingerprint_algorithm IS NOT NEW.current_fingerprint_algorithm OR "
    "plan.fingerprint_version IS NOT NEW.current_fingerprint_version OR "
    "plan.source_template_id IS NOT NEW.source_mapping_template_id OR "
    "plan.source_template_version_id IS NOT NEW.source_mapping_template_version_id))) "
    "BEGIN SELECT RAISE(ABORT, 'current mapping does not match execution plan'); END",
    "CREATE TRIGGER validate_import_batch_execution_plan_insert "
    "BEFORE INSERT ON import_batch_execution_plans "
    "WHEN NOT EXISTS (SELECT 1 FROM import_batches AS batch WHERE batch.id = NEW.batch_id "
    "AND NEW.mapping_revision IN (batch.mapping_revision, batch.mapping_revision + 1)) OR "
    "EXISTS (SELECT 1 FROM import_batches AS batch WHERE batch.id = NEW.batch_id "
    "AND batch.mapping_revision = NEW.mapping_revision AND ("
    "NEW.origin IS NOT batch.current_mapping_origin OR "
    "NEW.profile_id IS NOT batch.current_profile_id OR "
    "NEW.profile_version IS NOT batch.current_profile_version OR "
    "NEW.provider IS NOT batch.current_provider OR "
    "NEW.fingerprint_algorithm IS NOT batch.current_fingerprint_algorithm OR "
    "NEW.fingerprint_version IS NOT batch.current_fingerprint_version OR "
    "NEW.source_template_id IS NOT batch.source_mapping_template_id OR "
    "NEW.source_template_version_id IS NOT batch.source_mapping_template_version_id)) "
    "BEGIN SELECT RAISE(ABORT, 'execution plan does not match current mapping'); END",
)

for _trigger in _SQLITE_IMPORT_TRIGGERS:
    event.listen(Base.metadata, "after_create", DDL(_trigger).execute_if(dialect="sqlite"))
