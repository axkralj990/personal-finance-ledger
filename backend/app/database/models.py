from __future__ import annotations

import enum
import uuid
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import (
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
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    return datetime.now(UTC)


class Provider(enum.StrEnum):
    LEGACY = "LEGACY"
    REVOLUT = "REVOLUT"
    DBS = "DBS"
    MASTERCARD = "MASTERCARD"
    MANUAL = "MANUAL"


class BatchStatus(enum.StrEnum):
    UPLOADED = "UPLOADED"
    PARSED = "PARSED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    READY = "READY"
    COMMITTED = "COMMITTED"
    FAILED = "FAILED"
    DELETED = "DELETED"


class TransactionKind(enum.StrEnum):
    EXPENSE = "EXPENSE"
    INCOME = "INCOME"
    REFUND = "REFUND"
    FEE = "FEE"
    TRANSFER = "TRANSFER"


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
    PROVIDER = "PROVIDER"
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


enum_options = {"native_enum": False, "create_constraint": True, "validate_strings": True}


class Base(DeclarativeBase):
    pass


class SourceAccount(Base):
    __tablename__ = "source_accounts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    provider: Mapped[Provider] = mapped_column(Enum(Provider, **enum_options), index=True)
    display_name: Mapped[str] = mapped_column(String(120), unique=True)
    default_currency: Mapped[str] = mapped_column(String(3))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    __table_args__ = (CheckConstraint("length(default_currency) = 3"),)


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
    source_account_id: Mapped[str] = mapped_column(ForeignKey("source_accounts.id"), index=True)
    original_filename: Mapped[str] = mapped_column(String(255))
    retained_path: Mapped[str | None] = mapped_column(String(1024))
    file_sha256: Mapped[str] = mapped_column(String(64))
    parser_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[BatchStatus] = mapped_column(Enum(BatchStatus, **enum_options), index=True)
    total_rows: Mapped[int] = mapped_column(Integer, default=0)
    included_rows: Mapped[int] = mapped_column(Integer, default=0)
    ignored_rows: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    committed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    account: Mapped[SourceAccount] = relationship()
    staged_rows: Mapped[list[StagedTransaction]] = relationship(
        back_populates="batch", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index(
            "uq_import_batch_file_active",
            "source_account_id",
            "file_sha256",
            unique=True,
            sqlite_where=text("status != 'DELETED'"),
        ),
    )


class StagedTransaction(Base):
    __tablename__ = "staged_transactions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    batch_id: Mapped[str] = mapped_column(ForeignKey("import_batches.id", ondelete="CASCADE"))
    ledger_account_id: Mapped[str] = mapped_column(ForeignKey("source_accounts.id"), index=True)
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
    ledger_account: Mapped[SourceAccount] = relationship()

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
    source_account_id: Mapped[str] = mapped_column(ForeignKey("source_accounts.id"), index=True)
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

    account: Mapped[SourceAccount] = relationship()
    category: Mapped[Category | None] = relationship(foreign_keys=[category_id])
    subcategory: Mapped[Subcategory | None] = relationship(foreign_keys=[subcategory_id])

    __table_args__ = (
        UniqueConstraint("source_account_id", "row_fingerprint"),
        CheckConstraint("length(currency) = 3"),
        CheckConstraint("subcategory_id IS NULL OR category_id IS NOT NULL"),
        ForeignKeyConstraint(
            ["subcategory_id", "category_id"],
            ["subcategories.id", "subcategories.category_id"],
            name="fk_transaction_taxonomy_parent",
        ),
        Index(
            "uq_transaction_native_id",
            "source_account_id",
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
    source_account_id: Mapped[str | None] = mapped_column(ForeignKey("source_accounts.id"))
    provider: Mapped[Provider | None] = mapped_column(Enum(Provider, **enum_options))
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
            "(scope = 'GLOBAL' AND source_account_id IS NULL AND provider IS NULL) OR "
            "(scope = 'PROVIDER' AND source_account_id IS NULL AND provider IS NOT NULL) OR "
            "(scope = 'ACCOUNT' AND source_account_id IS NOT NULL AND provider IS NULL)",
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
