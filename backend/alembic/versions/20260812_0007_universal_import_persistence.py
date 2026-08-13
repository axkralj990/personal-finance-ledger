"""Add universal import persistence foundations.

Revision ID: 20260812_0007
Revises: 20260811_0006
"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_0007"
down_revision: str | None = "20260811_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OLD_BATCH_STATUSES = (
    "UPLOADED",
    "PARSED",
    "NEEDS_REVIEW",
    "READY",
    "COMMITTED",
    "FAILED",
    "DELETED",
)
NEW_BATCH_STATUSES = (
    "UPLOADED",
    "AWAITING_MAPPING",
    "STAGING",
    "PARSED",
    "NEEDS_REVIEW",
    "READY",
    "COMMITTED",
    "FAILED",
    "DELETED",
)
TEMPLATE_ORIGINS = ("PREDEFINED", "LLM_CONFIRMED", "MANUAL")
PLAN_KINDS = ("GUIDED_MAPPING", "ADAPTER_PROFILE")
SUGGESTION_OUTCOMES = (
    "SUCCEEDED",
    "AUTHENTICATION_ERROR",
    "PERMISSION_ERROR",
    "CONNECTION_ERROR",
    "TIMEOUT",
    "RATE_LIMITED",
    "REFUSED",
    "PROVIDER_ERROR",
    "INVALID_OUTPUT",
    "STALE",
)
PROVIDERS = ("LEGACY", "REVOLUT", "DBS", "MASTERCARD", "MANUAL")
LEGACY_ADAPTER_PROFILES = {
    "LEGACY": ("legacy", "1"),
    "REVOLUT": ("revolut", "1"),
    "DBS": ("dbs", "1"),
    "MASTERCARD": ("mastercard", "2"),
}


def upgrade() -> None:
    _require_safe_sqlite_rebuild_connection()
    op.create_table(
        "import_mapping_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("structural_signature", sa.String(64), nullable=False),
        sa.Column(
            "source_account_id",
            sa.String(36),
            sa.ForeignKey("source_accounts.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "origin",
            sa.Enum(
                *TEMPLATE_ORIGINS,
                name="importmappingtemplateorigin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("revision >= 1", name="ck_import_mapping_templates_revision"),
        sa.CheckConstraint(
            "origin != 'PREDEFINED' OR is_active = 1",
            name="ck_import_mapping_templates_predefined_active",
        ),
    )
    op.create_index(
        "ix_import_mapping_templates_match",
        "import_mapping_templates",
        ["structural_signature", "source_account_id", "is_active"],
    )
    op.create_index(
        "uq_import_mapping_templates_global_name",
        "import_mapping_templates",
        ["name"],
        unique=True,
        sqlite_where=sa.text("source_account_id IS NULL"),
    )
    op.create_index(
        "uq_import_mapping_templates_account_name",
        "import_mapping_templates",
        ["source_account_id", "name"],
        unique=True,
        sqlite_where=sa.text("source_account_id IS NOT NULL"),
    )

    op.create_table(
        "import_mapping_template_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "template_id",
            sa.String(36),
            sa.ForeignKey("import_mapping_templates.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "execution_plan_kind",
            sa.Enum(
                *PLAN_KINDS,
                name="importexecutionplankind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("execution_plan_schema_version", sa.String(40), nullable=False),
        sa.Column("execution_plan_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("version >= 1", name="ck_import_mapping_template_versions_version"),
        sa.UniqueConstraint("template_id", "version", name="uq_import_mapping_template_version"),
        sa.UniqueConstraint("id", "template_id", name="uq_import_mapping_template_version_owner"),
    )

    _upgrade_import_batches()
    op.create_table(
        "import_batch_execution_plans",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("import_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("mapping_revision", sa.Integer(), nullable=False),
        sa.Column(
            "kind",
            sa.Enum(
                *PLAN_KINDS,
                name="importexecutionplankind",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column(
            "origin",
            sa.Enum(
                *TEMPLATE_ORIGINS,
                name="importmappingtemplateorigin",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column(
            "source_template_id",
            sa.String(36),
            sa.ForeignKey("import_mapping_templates.id", ondelete="RESTRICT"),
        ),
        sa.Column("source_template_version_id", sa.String(36)),
        sa.Column("profile_id", sa.String(120)),
        sa.Column("profile_version", sa.String(40)),
        sa.Column(
            "provider",
            sa.Enum(*PROVIDERS, name="provider", native_enum=False, create_constraint=True),
        ),
        sa.Column("fingerprint_algorithm", sa.String(80), nullable=False),
        sa.Column("fingerprint_version", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("mapping_revision >= 1", name="ck_import_execution_plans_revision"),
        sa.CheckConstraint(
            "(source_template_id IS NULL AND source_template_version_id IS NULL) OR "
            "(source_template_id IS NOT NULL AND source_template_version_id IS NOT NULL)",
            name="ck_import_execution_plans_source_template",
        ),
        sa.CheckConstraint(
            "(kind = 'GUIDED_MAPPING' AND profile_id IS NULL AND "
            "profile_version IS NULL AND provider IS NULL) OR "
            "(kind = 'ADAPTER_PROFILE' AND profile_id IS NOT NULL AND "
            "profile_version IS NOT NULL AND provider IS NOT NULL)",
            name="ck_import_execution_plans_kind",
        ),
        sa.ForeignKeyConstraint(
            ["source_template_version_id", "source_template_id"],
            ["import_mapping_template_versions.id", "import_mapping_template_versions.template_id"],
            name="fk_import_execution_plan_template_version",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("batch_id", "mapping_revision", name="uq_import_batch_execution_plan"),
    )
    op.create_table(
        "import_mapping_suggestion_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "batch_id",
            sa.String(36),
            sa.ForeignKey("import_batches.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("batch_revision", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("provider_request_id", sa.String(255)),
        sa.Column("prompt_version", sa.String(40), nullable=False),
        sa.Column("schema_version", sa.String(40), nullable=False),
        sa.Column("payload_sha256", sa.String(64), nullable=False),
        sa.Column("consented_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.Column(
            "outcome",
            sa.Enum(
                *SUGGESTION_OUTCOMES,
                name="importmappingsuggestionoutcome",
                native_enum=False,
                create_constraint=True,
            ),
            nullable=False,
        ),
        sa.Column("execution_plan_json", sa.JSON()),
        sa.Column("error_class", sa.String(160)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("batch_revision >= 1", name="ck_import_suggestions_batch_revision"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_import_suggestions_attempt_number"),
        sa.CheckConstraint("duration_ms >= 0", name="ck_import_suggestions_duration"),
        sa.CheckConstraint(
            "length(payload_sha256) = 64", name="ck_import_suggestions_payload_sha256"
        ),
        sa.UniqueConstraint(
            "batch_id", "attempt_number", name="uq_import_mapping_suggestion_attempt"
        ),
    )
    op.create_index(
        "ix_import_mapping_suggestions_batch_created",
        "import_mapping_suggestion_attempts",
        ["batch_id", "created_at"],
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER prevent_import_mapping_template_version_update "
            "BEFORE UPDATE ON import_mapping_template_versions "
            "BEGIN SELECT RAISE(ABORT, 'import mapping template versions are immutable'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER prevent_import_mapping_template_version_delete "
            "BEFORE DELETE ON import_mapping_template_versions "
            "BEGIN SELECT RAISE(ABORT, 'import mapping template versions are retained'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER prevent_import_batch_execution_plan_update "
            "BEFORE UPDATE ON import_batch_execution_plans "
            "BEGIN SELECT RAISE(ABORT, 'import batch execution plans are immutable'); END"
        )
    )
    op.execute(
        sa.text(
            "CREATE TRIGGER prevent_import_batch_execution_plan_delete "
            "BEFORE DELETE ON import_batch_execution_plans "
            "BEGIN SELECT RAISE(ABORT, 'import batch execution plans are retained'); END"
        )
    )
    op.execute(
        sa.text(
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
            "BEGIN SELECT RAISE(ABORT, 'current mapping does not match execution plan'); END"
        )
    )
    op.execute(
        sa.text(
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
            "BEGIN SELECT RAISE(ABORT, 'execution plan does not match current mapping'); END"
        )
    )

    connection = op.get_bind()
    rows = connection.execute(
        sa.text(
            "SELECT import_batches.id, import_batches.parser_version, "
            "source_accounts.provider, import_batches.created_at "
            "FROM import_batches JOIN source_accounts "
            "ON source_accounts.id = import_batches.source_account_id"
        )
    ).mappings()
    for row in rows:
        profile = LEGACY_ADAPTER_PROFILES.get(row["provider"])
        if profile is None or row["parser_version"] != profile[1]:
            continue
        profile_id, profile_version = profile
        plan = {
            "plan_type": "adapter",
            "schema_version": "adapter-v1",
            "profile_id": profile_id,
            "profile_version": profile_version,
            "configuration": {},
        }
        connection.execute(
            sa.text(
                "INSERT INTO import_batch_execution_plans ("
                "id, batch_id, mapping_revision, kind, schema_version, plan_json, origin, "
                "profile_id, profile_version, provider, fingerprint_algorithm, "
                "fingerprint_version, created_at) VALUES ("
                ":id, :batch_id, 1, 'ADAPTER_PROFILE', 'adapter-v1', :plan_json, 'PREDEFINED', "
                ":profile_id, :profile_version, :provider, 'adapter-row', :profile_version, "
                ":created_at)"
            ),
            {
                "id": _legacy_plan_id(row["id"]),
                "batch_id": row["id"],
                "plan_json": json.dumps(plan, separators=(",", ":")),
                "profile_id": profile_id,
                "profile_version": profile_version,
                "provider": row["provider"],
                "created_at": row["created_at"],
            },
        )
        connection.execute(
            sa.text(
                "UPDATE import_batches SET mapping_revision = 1, "
                "current_mapping_origin = 'PREDEFINED', current_profile_id = :profile_id, "
                "current_profile_version = :profile_version, current_provider = :provider, "
                "current_fingerprint_algorithm = 'adapter-row', "
                "current_fingerprint_version = :profile_version WHERE id = :batch_id"
            ),
            {
                "batch_id": row["id"],
                "profile_id": profile_id,
                "profile_version": profile_version,
                "provider": row["provider"],
            },
        )


def downgrade() -> None:
    connection = op.get_bind()
    _require_safe_sqlite_rebuild_connection()
    _refuse_lossy_downgrade(connection)
    op.execute(sa.text("DROP TRIGGER validate_import_batch_execution_plan_insert"))
    op.execute(sa.text("DROP TRIGGER validate_import_batch_current_mapping_update"))
    op.execute(sa.text("DROP TRIGGER prevent_import_batch_execution_plan_delete"))
    op.execute(sa.text("DROP TRIGGER prevent_import_batch_execution_plan_update"))
    op.execute(sa.text("DROP TRIGGER prevent_import_mapping_template_version_delete"))
    op.execute(sa.text("DROP TRIGGER prevent_import_mapping_template_version_update"))
    op.drop_index(
        "ix_import_mapping_suggestions_batch_created",
        table_name="import_mapping_suggestion_attempts",
    )
    op.drop_table("import_mapping_suggestion_attempts")
    op.drop_table("import_batch_execution_plans")

    _downgrade_import_batches()

    op.drop_table("import_mapping_template_versions")
    op.drop_index("uq_import_mapping_templates_account_name", table_name="import_mapping_templates")
    op.drop_index("uq_import_mapping_templates_global_name", table_name="import_mapping_templates")
    op.drop_index("ix_import_mapping_templates_match", table_name="import_mapping_templates")
    op.drop_table("import_mapping_templates")


def _upgrade_import_batches() -> None:
    connection = op.get_bind()
    old_status = sa.Enum(
        *OLD_BATCH_STATUSES,
        name="batchstatus",
        native_enum=False,
        create_constraint=True,
    )
    new_status = sa.Enum(
        *NEW_BATCH_STATUSES,
        name="batchstatus",
        native_enum=False,
        create_constraint=True,
    )
    with op.batch_alter_table("import_batches", recreate="always") as batch:
        batch.alter_column(
            "status",
            existing_type=old_status,
            type_=new_status,
            existing_nullable=False,
        )
        batch.add_column(
            sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1"))
        )
        batch.add_column(
            sa.Column(
                "inspection_json",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            )
        )
        batch.add_column(sa.Column("inspection_version", sa.String(40)))
        batch.add_column(sa.Column("structural_signature", sa.String(64)))
        batch.add_column(
            sa.Column("mapping_revision", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch.add_column(sa.Column("current_mapping_origin", sa.String(13)))
        batch.add_column(sa.Column("current_profile_id", sa.String(120)))
        batch.add_column(sa.Column("current_profile_version", sa.String(40)))
        batch.add_column(sa.Column("current_provider", sa.String(10)))
        batch.add_column(sa.Column("current_fingerprint_algorithm", sa.String(80)))
        batch.add_column(sa.Column("current_fingerprint_version", sa.String(40)))
        batch.add_column(
            sa.Column(
                "current_mapping_diagnostics",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'[]'"),
            )
        )
        batch.add_column(sa.Column("source_mapping_template_id", sa.String(36)))
        batch.add_column(sa.Column("source_mapping_template_version_id", sa.String(36)))
        batch.create_check_constraint("ck_import_batches_revision", "revision >= 1")
        batch.create_check_constraint("ck_import_batches_mapping_revision", "mapping_revision >= 0")
        batch.create_check_constraint(
            "ck_import_batches_current_mapping",
            "(current_mapping_origin IS NULL AND "
            "current_profile_id IS NULL AND current_profile_version IS NULL AND "
            "current_provider IS NULL AND current_fingerprint_algorithm IS NULL AND "
            "current_fingerprint_version IS NULL AND source_mapping_template_id IS NULL AND "
            "source_mapping_template_version_id IS NULL) OR "
            "(mapping_revision >= 1 AND current_mapping_origin IS NOT NULL AND "
            "current_fingerprint_algorithm IS NOT NULL AND current_fingerprint_version IS NOT NULL "
            "AND ((current_profile_id IS NULL AND current_profile_version IS NULL AND "
            "current_provider IS NULL) OR (current_profile_id IS NOT NULL AND "
            "current_profile_version IS NOT NULL AND current_provider IS NOT NULL)))",
        )
        batch.create_check_constraint(
            "importmappingtemplateorigin",
            "current_mapping_origin IN ('PREDEFINED', 'LLM_CONFIRMED', 'MANUAL')",
        )
        batch.create_check_constraint(
            "provider",
            "current_provider IN ('LEGACY', 'REVOLUT', 'DBS', 'MASTERCARD', 'MANUAL')",
        )
        batch.create_check_constraint(
            "ck_import_batches_source_template",
            "(source_mapping_template_id IS NULL AND "
            "source_mapping_template_version_id IS NULL) OR "
            "(source_mapping_template_id IS NOT NULL AND "
            "source_mapping_template_version_id IS NOT NULL)",
        )
        batch.create_foreign_key(
            "fk_import_batches_source_mapping_template",
            "import_mapping_templates",
            ["source_mapping_template_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_import_batch_mapping_template_version",
            "import_mapping_template_versions",
            ["source_mapping_template_version_id", "source_mapping_template_id"],
            ["id", "template_id"],
            ondelete="RESTRICT",
        )
    _validate_migration_integrity(connection)


def _downgrade_import_batches() -> None:
    connection = op.get_bind()
    new_status = sa.Enum(
        *NEW_BATCH_STATUSES,
        name="batchstatus",
        native_enum=False,
        create_constraint=True,
    )
    old_status = sa.Enum(
        *OLD_BATCH_STATUSES,
        name="batchstatus",
        native_enum=False,
        create_constraint=True,
    )
    with op.batch_alter_table("import_batches", recreate="always") as batch:
        batch.drop_constraint("fk_import_batch_mapping_template_version", type_="foreignkey")
        batch.drop_constraint("fk_import_batches_source_mapping_template", type_="foreignkey")
        batch.drop_constraint("ck_import_batches_source_template", type_="check")
        batch.drop_constraint("provider", type_="check")
        batch.drop_constraint("importmappingtemplateorigin", type_="check")
        batch.drop_constraint("ck_import_batches_current_mapping", type_="check")
        batch.drop_constraint("ck_import_batches_mapping_revision", type_="check")
        batch.drop_constraint("ck_import_batches_revision", type_="check")
        for column_name in (
            "source_mapping_template_version_id",
            "source_mapping_template_id",
            "current_mapping_diagnostics",
            "current_fingerprint_version",
            "current_fingerprint_algorithm",
            "current_provider",
            "current_profile_version",
            "current_profile_id",
            "current_mapping_origin",
            "mapping_revision",
            "structural_signature",
            "inspection_version",
            "inspection_json",
            "revision",
        ):
            batch.drop_column(column_name)
        batch.alter_column(
            "status",
            existing_type=new_status,
            type_=old_status,
            existing_nullable=False,
        )
    _validate_migration_integrity(connection)


def _require_safe_sqlite_rebuild_connection() -> None:
    connection = op.get_bind()
    if connection.dialect.name != "sqlite":
        raise RuntimeError("Universal import persistence currently supports SQLite only")
    if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 0:
        raise RuntimeError(
            "Migration 0007 requires a dedicated SQLite connection with foreign_keys disabled"
        )


def _validate_migration_integrity(connection: sa.Connection) -> None:
    violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
    if violations:
        raise RuntimeError(f"Foreign key check failed after import migration: {violations!r}")
    integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
    if integrity != "ok":
        raise RuntimeError(f"SQLite integrity check failed after import migration: {integrity}")


def _legacy_plan_id(batch_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"personal-finances:legacy-import-plan:{batch_id}"))


def _refuse_lossy_downgrade(connection: sa.Connection) -> None:
    has_templates = connection.scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM import_mapping_templates)")
    )
    has_suggestions = connection.scalar(
        sa.text("SELECT EXISTS(SELECT 1 FROM import_mapping_suggestion_attempts)")
    )
    if has_templates or has_suggestions:
        raise RuntimeError(
            "Cannot downgrade universal import persistence while post-upgrade data exists"
        )

    batches = connection.execute(
        sa.text(
            "SELECT import_batches.*, source_accounts.provider FROM import_batches "
            "JOIN source_accounts ON source_accounts.id = import_batches.source_account_id"
        )
    ).mappings()
    expected_plan_batch_ids: set[str] = set()
    for batch in batches:
        profile = LEGACY_ADAPTER_PROFILES.get(batch["provider"])
        can_have_legacy_plan = profile is not None and batch["parser_version"] == profile[1]
        expected_mapping_revision = 1 if can_have_legacy_plan else 0
        if (
            batch["status"] not in OLD_BATCH_STATUSES
            or batch["parser_version"] == "universal-import-v1"
            or batch["revision"] != 1
            or _json_value(batch["inspection_json"]) != {}
            or batch["inspection_version"] is not None
            or batch["structural_signature"] is not None
            or _json_value(batch["current_mapping_diagnostics"]) != []
            or batch["source_mapping_template_id"] is not None
            or batch["source_mapping_template_version_id"] is not None
            or batch["mapping_revision"] != expected_mapping_revision
        ):
            raise RuntimeError(
                "Cannot downgrade universal import persistence while post-upgrade data exists"
            )
        if can_have_legacy_plan:
            profile_id, profile_version = profile
            if (
                batch["current_mapping_origin"] != "PREDEFINED"
                or batch["current_profile_id"] != profile_id
                or batch["current_profile_version"] != profile_version
                or batch["current_provider"] != batch["provider"]
                or batch["current_fingerprint_algorithm"] != "adapter-row"
                or batch["current_fingerprint_version"] != profile_version
            ):
                raise RuntimeError(
                    "Cannot downgrade universal import persistence while post-upgrade data exists"
                )
            expected_plan_batch_ids.add(batch["id"])
        elif any(
            batch[column] is not None
            for column in (
                "current_mapping_origin",
                "current_profile_id",
                "current_profile_version",
                "current_provider",
                "current_fingerprint_algorithm",
                "current_fingerprint_version",
            )
        ):
            raise RuntimeError(
                "Cannot downgrade universal import persistence while post-upgrade data exists"
            )

    plans = connection.execute(sa.text("SELECT * FROM import_batch_execution_plans")).mappings()
    seen_plan_batch_ids: set[str] = set()
    for plan in plans:
        profile = LEGACY_ADAPTER_PROFILES.get(plan["provider"])
        expected_json = (
            {
                "plan_type": "adapter",
                "schema_version": "adapter-v1",
                "profile_id": profile[0],
                "profile_version": profile[1],
                "configuration": {},
            }
            if profile is not None
            else None
        )
        if (
            plan["batch_id"] not in expected_plan_batch_ids
            or plan["id"] != _legacy_plan_id(plan["batch_id"])
            or plan["mapping_revision"] != 1
            or plan["kind"] != "ADAPTER_PROFILE"
            or plan["schema_version"] != "adapter-v1"
            or plan["origin"] != "PREDEFINED"
            or plan["source_template_id"] is not None
            or plan["source_template_version_id"] is not None
            or profile is None
            or plan["profile_id"] != profile[0]
            or plan["profile_version"] != profile[1]
            or plan["fingerprint_algorithm"] != "adapter-row"
            or plan["fingerprint_version"] != profile[1]
            or _json_value(plan["plan_json"]) != expected_json
        ):
            raise RuntimeError(
                "Cannot downgrade universal import persistence while post-upgrade data exists"
            )
        seen_plan_batch_ids.add(plan["batch_id"])
    if seen_plan_batch_ids != expected_plan_batch_ids:
        raise RuntimeError(
            "Cannot downgrade universal import persistence while post-upgrade data exists"
        )


def _json_value(value: object) -> object:
    return json.loads(value) if isinstance(value, str) else value
