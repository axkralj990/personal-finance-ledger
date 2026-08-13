from __future__ import annotations

import json
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, create_engine, event, inspect
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DatabaseError, IntegrityError

from backend.app.database.models import Base


def test_populated_upgrade_preserves_imports_and_backfills_valid_provenance(
    tmp_path: Path,
) -> None:
    engine, config = _database_at_0006(tmp_path)
    with engine.begin() as connection:
        account_ids = _account_ids(connection)
        _insert_batch(connection, "manual-draft", account_ids["MANUAL"], "manual-1", "UPLOADED")
        _insert_batch(connection, "adapter-draft", account_ids["REVOLUT"], "1", "PARSED")
        _insert_batch(connection, "adapter-committed", account_ids["MASTERCARD"], "2", "COMMITTED")
        _insert_batch(connection, "old-adapter", account_ids["DBS"], "0", "NEEDS_REVIEW")
        for batch_id, account_id in (
            ("manual-draft", account_ids["MANUAL"]),
            ("adapter-draft", account_ids["REVOLUT"]),
            ("adapter-committed", account_ids["MASTERCARD"]),
        ):
            _insert_staged_row(connection, batch_id, account_id)
        _insert_transaction(connection, "adapter-committed", account_ids["MASTERCARD"])
    command.upgrade(config, "20260812_0007")
    with engine.begin() as connection:
        batches = {
            row.id: row
            for row in connection.exec_driver_sql(
                "SELECT id, status, revision, inspection_json, inspection_version, "
                "structural_signature, mapping_revision, current_profile_id, "
                "current_profile_version, current_provider, current_fingerprint_algorithm, "
                "current_fingerprint_version FROM import_batches"
            ).mappings()
        }
        assert {batch_id: row.status for batch_id, row in batches.items()} == {
            "manual-draft": "UPLOADED",
            "adapter-draft": "PARSED",
            "adapter-committed": "COMMITTED",
            "old-adapter": "NEEDS_REVIEW",
        }
        for batch in batches.values():
            assert batch.revision == 1
            assert json.loads(batch.inspection_json) == {}
            assert batch.inspection_version is None
            assert batch.structural_signature is None

        assert batches["manual-draft"].mapping_revision == 0
        assert batches["manual-draft"].current_profile_id is None
        assert batches["old-adapter"].mapping_revision == 0
        assert batches["old-adapter"].current_profile_id is None
        assert (
            batches["adapter-draft"].mapping_revision,
            batches["adapter-draft"].current_profile_id,
            batches["adapter-draft"].current_profile_version,
            batches["adapter-draft"].current_provider,
            batches["adapter-draft"].current_fingerprint_algorithm,
            batches["adapter-draft"].current_fingerprint_version,
        ) == (1, "revolut", "1", "REVOLUT", "adapter-row", "1")
        assert (
            batches["adapter-committed"].mapping_revision,
            batches["adapter-committed"].current_profile_id,
            batches["adapter-committed"].current_profile_version,
            batches["adapter-committed"].current_provider,
            batches["adapter-committed"].current_fingerprint_version,
        ) == (1, "mastercard", "2", "MASTERCARD", "2")

        plans = list(
            connection.exec_driver_sql(
                "SELECT batch_id, mapping_revision, profile_id, profile_version, provider, "
                "fingerprint_version, plan_json FROM import_batch_execution_plans "
                "ORDER BY batch_id"
            ).mappings()
        )
        assert [plan.batch_id for plan in plans] == ["adapter-committed", "adapter-draft"]
        assert [json.loads(plan.plan_json)["profile_version"] for plan in plans] == ["2", "1"]
        assert connection.exec_driver_sql("SELECT count(*) FROM staged_transactions").scalar() == 3
        assert connection.exec_driver_sql("SELECT count(*) FROM transactions").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    engine.dispose()


def test_import_history_is_immutable_without_blocking_batch_soft_delete(tmp_path: Path) -> None:
    engine, config = _database_at_0006(tmp_path)
    with engine.begin() as connection:
        account_id = _account_ids(connection)["REVOLUT"]
        _insert_batch(connection, "adapter-draft", account_id, "1", "PARSED")
    command.upgrade(config, "20260812_0007")

    with engine.connect() as connection:
        for statement in (
            "UPDATE import_batch_execution_plans SET schema_version = 'changed'",
            "DELETE FROM import_batch_execution_plans",
        ):
            with pytest.raises(DatabaseError):
                connection.exec_driver_sql(statement)
            connection.rollback()
        connection.exec_driver_sql(
            "UPDATE import_batches SET status = 'DELETED' WHERE id = 'adapter-draft'"
        )
        connection.commit()
        assert (
            connection.exec_driver_sql("SELECT count(*) FROM import_batch_execution_plans").scalar()
            == 1
        )

        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "UPDATE import_batches SET mapping_revision = 0 WHERE id = 'adapter-draft'"
            )
        connection.rollback()
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "UPDATE import_batches SET current_profile_version = '9' WHERE id = 'adapter-draft'"
            )
        connection.rollback()
        connection.exec_driver_sql(
            "UPDATE import_batches SET current_mapping_origin = NULL, current_profile_id = NULL, "
            "current_profile_version = NULL, current_provider = NULL, "
            "current_fingerprint_algorithm = NULL, current_fingerprint_version = NULL "
            "WHERE id = 'adapter-draft'"
        )
        connection.commit()
        assert (
            connection.exec_driver_sql(
                "SELECT mapping_revision FROM import_batches WHERE id = 'adapter-draft'"
            ).scalar_one()
            == 1
        )
        assert (
            connection.exec_driver_sql(
                "SELECT count(*) FROM import_batch_execution_plans WHERE batch_id = 'adapter-draft'"
            ).scalar_one()
            == 1
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "UPDATE import_batches SET mapping_revision = 2 WHERE id = 'adapter-draft'"
            )
        connection.rollback()
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO import_batch_execution_plans ("
                "id, batch_id, mapping_revision, kind, schema_version, plan_json, origin, "
                "profile_id, profile_version, provider, fingerprint_algorithm, "
                "fingerprint_version, created_at) VALUES ("
                "'bad-plan', 'adapter-draft', 3, 'ADAPTER_PROFILE', 'adapter-v1', '{}', "
                "'PREDEFINED', 'revolut', '1', 'REVOLUT', 'adapter-row', '1', '2026-01-01')"
            )
        connection.rollback()
    engine.dispose()


def test_template_versions_are_immutable_and_foreign_keys_are_enforced(tmp_path: Path) -> None:
    engine, config = _database_at_0006(tmp_path)
    command.upgrade(config, "20260812_0007")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO import_mapping_templates ("
            "id, name, structural_signature, source_account_id, origin, is_active, revision, "
            "created_at, updated_at) VALUES ("
            "'template', 'Template', :signature, NULL, 'MANUAL', 1, 1, '2026-01-01', '2026-01-01')",
            {"signature": "a" * 64},
        )
        connection.exec_driver_sql(
            "INSERT INTO import_mapping_template_versions ("
            "id, template_id, version, execution_plan_kind, execution_plan_schema_version, "
            "execution_plan_json, created_at) VALUES ("
            "'version', 'template', 1, 'GUIDED_MAPPING', 'guided-v1', '{}', '2026-01-01')"
        )

    with engine.connect() as connection:
        for statement in (
            "UPDATE import_mapping_template_versions SET version = 2 WHERE id = 'version'",
            "DELETE FROM import_mapping_template_versions WHERE id = 'version'",
            "DELETE FROM import_mapping_templates WHERE id = 'template'",
        ):
            with pytest.raises(DatabaseError):
                connection.exec_driver_sql(statement)
            connection.rollback()
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO import_mapping_template_versions ("
                "id, template_id, version, execution_plan_kind, execution_plan_schema_version, "
                "execution_plan_json, created_at) VALUES ("
                "'orphan', 'missing', 1, 'GUIDED_MAPPING', 'guided-v1', '{}', '2026-01-01')"
            )
        connection.rollback()
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
    engine.dispose()


@pytest.mark.parametrize("post_upgrade_data", ["import", "template", "suggestion"])
def test_downgrade_refuses_post_upgrade_universal_import_data(
    tmp_path: Path, post_upgrade_data: str
) -> None:
    engine, config = _database_at_0006(tmp_path)
    with engine.begin() as connection:
        account_id = _account_ids(connection)["MANUAL"]
        _insert_batch(connection, "existing", account_id, "manual-1", "UPLOADED")
    command.upgrade(config, "20260812_0007")
    with engine.begin() as connection:
        if post_upgrade_data == "import":
            connection.exec_driver_sql(
                "UPDATE import_batches SET inspection_json = :inspection, "
                "inspection_version = 'inspection-v1', structural_signature = :signature "
                "WHERE id = 'existing'",
                {
                    "inspection": '{"inspection_version":"inspection-v1"}',
                    "signature": "b" * 64,
                },
            )
        elif post_upgrade_data == "template":
            connection.exec_driver_sql(
                "INSERT INTO import_mapping_templates ("
                "id, name, structural_signature, source_account_id, origin, is_active, revision, "
                "created_at, updated_at) VALUES ("
                "'new-template', 'New', :signature, NULL, 'MANUAL', 1, 1, "
                "'2026-01-01', '2026-01-01')",
                {"signature": "b" * 64},
            )
        else:
            connection.exec_driver_sql(
                "INSERT INTO import_mapping_suggestion_attempts ("
                "id, batch_id, batch_revision, attempt_number, model_name, "
                "provider_request_id, prompt_version, schema_version, payload_sha256, "
                "consented_at, started_at, completed_at, duration_ms, outcome, "
                "execution_plan_json, error_class, created_at) VALUES ("
                "'suggestion', 'existing', 1, 1, 'model', NULL, 'prompt-v1', "
                "'guided-v1', :sha, '2026-01-01', '2026-01-01', '2026-01-01', 1, "
                "'INVALID_OUTPUT', NULL, 'invalid', '2026-01-01')",
                {"sha": "c" * 64},
            )

    with pytest.raises(RuntimeError, match="post-upgrade data"):
        command.downgrade(config, "20260811_0006")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT version_num FROM alembic_version").scalar() == (
            "20260812_0007"
        )
        if post_upgrade_data == "import":
            assert connection.exec_driver_sql("SELECT count(*) FROM import_batches").scalar() == 1
        elif post_upgrade_data == "template":
            assert (
                connection.exec_driver_sql("SELECT count(*) FROM import_mapping_templates").scalar()
                == 1
            )
        else:
            assert (
                connection.exec_driver_sql(
                    "SELECT count(*) FROM import_mapping_suggestion_attempts"
                ).scalar()
                == 1
            )
    engine.dispose()


def test_clean_populated_upgrade_can_downgrade_without_losing_legacy_rows(tmp_path: Path) -> None:
    engine, config = _database_at_0006(tmp_path)
    with engine.begin() as connection:
        account_ids = _account_ids(connection)
        _insert_batch(connection, "manual-draft", account_ids["MANUAL"], "manual-1", "UPLOADED")
        _insert_batch(connection, "adapter-draft", account_ids["DBS"], "1", "READY")
        _insert_staged_row(connection, "manual-draft", account_ids["MANUAL"])
    command.upgrade(config, "20260812_0007")
    command.downgrade(config, "20260811_0006")
    with engine.begin() as connection:
        assert connection.exec_driver_sql(
            "SELECT id, status FROM import_batches ORDER BY id"
        ).all() == [("adapter-draft", "READY"), ("manual-draft", "UPLOADED")]
        assert connection.exec_driver_sql("SELECT count(*) FROM staged_transactions").scalar() == 1
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar() == "ok"
    engine.dispose()


def test_fresh_orm_schema_has_universal_import_invariants(tmp_path: Path) -> None:
    engine = _engine(tmp_path / "orm.sqlite3")
    Base.metadata.create_all(engine)
    inspector = inspect(engine)
    assert {
        "import_mapping_templates",
        "import_mapping_template_versions",
        "import_batch_execution_plans",
        "import_mapping_suggestion_attempts",
    } <= set(inspector.get_table_names())
    batch_checks = {
        constraint["name"] for constraint in inspector.get_check_constraints("import_batches")
    }
    assert "ck_import_batches_current_mapping" in batch_checks
    plan_foreign_keys = {
        constraint["name"]
        for constraint in inspector.get_foreign_keys("import_batch_execution_plans")
    }
    assert "fk_import_execution_plan_template_version" in plan_foreign_keys
    with engine.connect() as connection:
        triggers = {
            row.name
            for row in connection.exec_driver_sql(
                "SELECT name FROM sqlite_schema WHERE type = 'trigger'"
            ).mappings()
        }
    assert {
        "prevent_import_mapping_template_version_update",
        "prevent_import_mapping_template_version_delete",
        "prevent_import_batch_execution_plan_update",
        "prevent_import_batch_execution_plan_delete",
        "validate_import_batch_current_mapping_update",
        "validate_import_batch_execution_plan_insert",
    } <= triggers
    engine.dispose()


def _database_at_0006(tmp_path: Path) -> tuple[Engine, Config]:
    engine = _engine(tmp_path / "migration.sqlite3")
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", str(engine.url))
    command.upgrade(config, "20260811_0006")
    return engine, config


def _engine(path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{path}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def _account_ids(connection: Connection) -> dict[str, str]:
    return {
        row.provider: row.id
        for row in connection.exec_driver_sql(
            "SELECT id, provider FROM source_accounts ORDER BY display_name"
        ).mappings()
    }


def _insert_batch(
    connection: Connection,
    batch_id: str,
    account_id: str,
    parser_version: str,
    status: str,
) -> None:
    connection.exec_driver_sql(
        "INSERT INTO import_batches ("
        "id, source_account_id, original_filename, retained_path, file_sha256, parser_version, "
        "status, total_rows, included_rows, ignored_rows, error_message, created_at, updated_at, "
        "committed_at) VALUES ("
        ":id, :account_id, :filename, NULL, :sha, :parser_version, :status, 1, 1, 0, NULL, "
        "'2026-01-01', '2026-01-01', :committed_at)",
        {
            "id": batch_id,
            "account_id": account_id,
            "filename": f"{batch_id}.csv",
            "sha": batch_id.ljust(64, "0"),
            "parser_version": parser_version,
            "status": status,
            "committed_at": "2026-01-01" if status == "COMMITTED" else None,
        },
    )


def _insert_staged_row(connection: Connection, batch_id: str, account_id: str) -> None:
    connection.exec_driver_sql(
        "INSERT INTO staged_transactions ("
        "id, batch_id, ledger_account_id, row_number, raw_json, transaction_date, "
        "transaction_at, description, normalized_description, amount_minor, currency, kind, "
        "source_native_id, row_fingerprint, predicted_category_id, predicted_subcategory_id, "
        "prediction_confidence, model_version_id, category_id, subcategory_id, validation_issues, "
        "duplicate_status, duplicate_candidate_id, duplicate_explanation, disposition, "
        "ignore_reason, remember_correction, revision, created_at, updated_at) VALUES ("
        ":id, :batch_id, :account_id, 1, '{}', '2026-01-01', NULL, 'row', 'row', -100, "
        "'EUR', 'EXPENSE', NULL, :fingerprint, NULL, NULL, NULL, NULL, NULL, NULL, '[]', "
        "'NONE', NULL, NULL, :disposition, NULL, 0, 1, '2026-01-01', '2026-01-01')",
        {
            "id": f"staged-{batch_id}",
            "batch_id": batch_id,
            "account_id": account_id,
            "fingerprint": batch_id.rjust(64, "f"),
            "disposition": "COMMITTED" if batch_id == "adapter-committed" else "PENDING",
        },
    )


def _insert_transaction(connection: Connection, batch_id: str, account_id: str) -> None:
    connection.exec_driver_sql(
        "INSERT INTO transactions ("
        "id, source_account_id, transaction_date, transaction_at, description, "
        "normalized_description, amount_minor, currency, kind, category_id, subcategory_id, "
        "source_native_id, row_fingerprint, import_batch_id, staged_transaction_id, is_excluded, "
        "exclusion_reason, revision, created_at, updated_at, corrected_at, excluded_at) VALUES ("
        "'committed-transaction', :account_id, '2026-01-01', NULL, 'row', 'row', -100, 'EUR', "
        "'EXPENSE', NULL, NULL, NULL, :fingerprint, :batch_id, :staged_id, 0, NULL, 1, "
        "'2026-01-01', '2026-01-01', NULL, NULL)",
        {
            "account_id": account_id,
            "fingerprint": batch_id.rjust(64, "f"),
            "batch_id": batch_id,
            "staged_id": f"staged-{batch_id}",
        },
    )
