from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect
from sqlalchemy.exc import IntegrityError


def test_populated_0007_upgrade_preserves_rows_audit_and_normalizes_kinds(
    tmp_path: Path,
) -> None:
    engine, config = _database_at_0007(tmp_path)
    with engine.begin() as connection:
        account = connection.exec_driver_sql(
            "SELECT id FROM source_accounts WHERE display_name = 'Revolut Personal EUR'"
        ).scalar_one()
        joint_account = connection.exec_driver_sql(
            "SELECT id FROM source_accounts WHERE display_name = 'Revolut Joint EUR'"
        ).scalar_one()
        dbs_account = connection.exec_driver_sql(
            "SELECT id FROM source_accounts WHERE display_name = 'DBS EUR'"
        ).scalar_one()
        category = connection.exec_driver_sql(
            "SELECT id FROM categories ORDER BY sort_order LIMIT 1"
        ).scalar_one()
        for rule_id, scope, provider, source_account_id in (
            ("global-rule", "GLOBAL", None, None),
            ("account-rule", "ACCOUNT", None, joint_account),
            ("dbs-rule", "PROVIDER", "DBS", None),
            ("revolut-rule", "PROVIDER", "REVOLUT", None),
        ):
            connection.exec_driver_sql(
                "INSERT INTO tag_rules (id, normalized_description, scope, source_account_id, "
                "provider, category_id, subcategory_id, is_enabled, created_at, updated_at) "
                "VALUES (:id, :id, :scope, :account, :provider, :category, NULL, 1, "
                "'2026-01-01', '2026-01-01')",
                {
                    "id": rule_id,
                    "scope": scope,
                    "account": source_account_id,
                    "provider": provider,
                    "category": category,
                },
            )
        connection.exec_driver_sql(
            "INSERT INTO import_batches ("
            "id, source_account_id, original_filename, retained_path, file_sha256, parser_version, "
            "status, revision, inspection_json, inspection_version, structural_signature, "
            "mapping_revision, current_mapping_origin, current_profile_id, "
            "current_profile_version, "
            "current_provider, current_fingerprint_algorithm, current_fingerprint_version, "
            "current_mapping_diagnostics, source_mapping_template_id, "
            "source_mapping_template_version_id, total_rows, included_rows, ignored_rows, "
            "error_message, created_at, updated_at, committed_at) VALUES ("
            "'batch', :account, 'legacy.csv', NULL, :sha, '1', 'COMMITTED', 1, '{}', NULL, NULL, "
            "1, 'PREDEFINED', 'revolut', '1', 'REVOLUT', 'adapter-row', '1', '[]', NULL, NULL, "
            "2, 1, 0, NULL, '2026-01-01', '2026-01-01', '2026-01-01')",
            {"account": account, "sha": "a" * 64},
        )
        connection.exec_driver_sql(
            "INSERT INTO import_batch_execution_plans ("
            "id, batch_id, mapping_revision, kind, schema_version, plan_json, origin, "
            "source_template_id, source_template_version_id, profile_id, profile_version, "
            "provider, fingerprint_algorithm, fingerprint_version, created_at) VALUES ("
            "'plan', 'batch', 1, 'ADAPTER_PROFILE', 'adapter-v1', '{}', 'PREDEFINED', NULL, NULL, "
            "'revolut', '1', 'REVOLUT', 'adapter-row', '1', '2026-01-01')"
        )
        for row_id, amount, kind in (("positive", 100, "FEE"), ("zero", 0, "REFUND")):
            connection.exec_driver_sql(
                "INSERT INTO staged_transactions ("
                "id, batch_id, ledger_account_id, row_number, raw_json, transaction_date, "
                "transaction_at, description, normalized_description, amount_minor, currency, "
                "kind, source_native_id, row_fingerprint, predicted_category_id, "
                "predicted_subcategory_id, prediction_confidence, model_version_id, category_id, "
                "subcategory_id, validation_issues, duplicate_status, duplicate_candidate_id, "
                "duplicate_explanation, disposition, ignore_reason, remember_correction, revision, "
                "created_at, updated_at) VALUES ("
                ":id, 'batch', :account, :row_number, '{}', '2026-01-01', NULL, :id, :id, "
                ":amount, 'EUR', :kind, NULL, :fingerprint, NULL, NULL, NULL, NULL, NULL, NULL, "
                "'[]', 'NONE', NULL, NULL, 'COMMITTED', NULL, 0, 1, '2026-01-01', '2026-01-01')",
                {
                    "id": row_id,
                    "account": account,
                    "row_number": 1 if row_id == "positive" else 2,
                    "amount": amount,
                    "kind": kind,
                    "fingerprint": row_id.ljust(64, "f"),
                },
            )
        connection.exec_driver_sql(
            "INSERT INTO transactions ("
            "id, source_account_id, transaction_date, transaction_at, description, "
            "normalized_description, amount_minor, currency, kind, category_id, subcategory_id, "
            "source_native_id, row_fingerprint, import_batch_id, staged_transaction_id, "
            "is_excluded, exclusion_reason, revision, created_at, updated_at, corrected_at, "
            "excluded_at) VALUES ("
            "'transaction', :account, '2026-01-01', NULL, 'positive', 'positive', 100, 'EUR', "
            "'FEE', NULL, NULL, NULL, :fingerprint, 'batch', 'positive', 0, NULL, 1, "
            "'2026-01-01', '2026-01-01', NULL, NULL)",
            {"account": account, "fingerprint": "positive".ljust(64, "f")},
        )

    command.upgrade(config, "20260813_0008")
    with engine.connect() as connection:
        assert "source_accounts" not in inspect(connection).get_table_names()
        assert connection.exec_driver_sql("SELECT count(*) FROM accounts").scalar_one() == 7
        assert {row[0] for row in connection.exec_driver_sql("SELECT name FROM accounts")} == {
            "Unknown",
            "Legacy historical ledger",
            "Revolut Personal EUR",
            "Revolut Joint EUR",
            "DBS EUR",
            "Mastercard EUR",
            "Manual EUR",
        }
        assert connection.exec_driver_sql(
            "SELECT id, name FROM accounts WHERE id = :id", {"id": account}
        ).one() == (account, "Revolut Personal EUR")
        assert connection.exec_driver_sql("SELECT kind FROM transactions").scalar_one() == "INCOME"
        assert connection.exec_driver_sql(
            "SELECT amount_minor, kind FROM staged_transactions ORDER BY row_number"
        ).all() == [(100, "INCOME"), (0, None)]
        assert connection.exec_driver_sql(
            "SELECT profile_id, provider, plan_json FROM import_batch_execution_plans"
        ).one() == ("revolut", "REVOLUT", "{}")
        assert "provider" not in {
            column[1] for column in connection.exec_driver_sql("PRAGMA table_info(tag_rules)")
        }
        assert connection.exec_driver_sql(
            "SELECT id, scope, account_id, is_enabled FROM tag_rules ORDER BY id"
        ).all() == [
            ("account-rule", "ACCOUNT", joint_account, 1),
            ("dbs-rule", "ACCOUNT", dbs_account, 1),
            ("global-rule", "GLOBAL", None, 1),
            ("revolut-rule", "GLOBAL", None, 0),
        ]
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
    engine.dispose()


def test_0008_kind_constraints_reject_raw_invalid_inserts_and_are_introspectable(
    tmp_path: Path,
) -> None:
    engine, config = _database_at_0007(tmp_path)
    command.upgrade(config, "20260813_0008")
    inspector = inspect(engine)
    for table in ("staged_transactions", "transactions"):
        constraints = {
            constraint["name"]: constraint["sqltext"]
            for constraint in inspector.get_check_constraints(table)
        }
        assert "transactionkind" in constraints
        assert "'INCOME'" in constraints["transactionkind"]
        assert "'EXPENSE'" in constraints["transactionkind"]
        assert "TRANSFER" not in constraints["transactionkind"]

    with engine.connect() as connection:
        account = connection.exec_driver_sql("SELECT id FROM accounts LIMIT 1").scalar_one()
        connection.exec_driver_sql(
            "INSERT INTO import_batches ("
            "id, account_id, original_filename, file_sha256, parser_version, status, revision, "
            "inspection_json, mapping_revision, current_mapping_diagnostics, total_rows, "
            "included_rows, ignored_rows, created_at, updated_at) VALUES ("
            "'raw-kind-batch', :account, 'raw.csv', :sha, 'test', 'UPLOADED', 1, '{}', 0, "
            "'[]', 1, 0, 0, '2026-01-01', '2026-01-01')",
            {"account": account, "sha": "d" * 64},
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO staged_transactions ("
                "id, batch_id, account_id, row_number, raw_json, amount_minor, kind, "
                "validation_issues, duplicate_status, disposition, remember_correction, revision, "
                "created_at, updated_at) VALUES ("
                "'raw-staged', 'raw-kind-batch', :account, 1, '{}', -1, 'TRANSFER', '[]', "
                "'NONE', 'PENDING', 0, 1, '2026-01-01', '2026-01-01')",
                {"account": account},
            )
        connection.rollback()

        connection.exec_driver_sql(
            "INSERT INTO import_batches ("
            "id, account_id, original_filename, file_sha256, parser_version, status, revision, "
            "inspection_json, mapping_revision, current_mapping_diagnostics, total_rows, "
            "included_rows, ignored_rows, created_at, updated_at) VALUES ("
            "'raw-kind-batch', :account, 'raw.csv', :sha, 'test', 'UPLOADED', 1, '{}', 0, "
            "'[]', 1, 0, 0, '2026-01-01', '2026-01-01')",
            {"account": account, "sha": "d" * 64},
        )
        connection.exec_driver_sql(
            "INSERT INTO staged_transactions ("
            "id, batch_id, account_id, row_number, raw_json, amount_minor, validation_issues, "
            "duplicate_status, disposition, remember_correction, revision, created_at, updated_at) "
            "VALUES ('raw-staged', 'raw-kind-batch', :account, 1, '{}', -1, '[]', 'NONE', "
            "'PENDING', 0, 1, '2026-01-01', '2026-01-01')",
            {"account": account},
        )
        with pytest.raises(IntegrityError):
            connection.exec_driver_sql(
                "INSERT INTO transactions ("
                "id, account_id, transaction_date, description, normalized_description, "
                "amount_minor, currency, kind, row_fingerprint, import_batch_id, "
                "staged_transaction_id, is_excluded, revision, created_at, updated_at) VALUES ("
                "'raw-transaction', :account, '2026-01-01', 'raw', 'raw', -1, 'EUR', "
                "'TRANSFER', :fingerprint, 'raw-kind-batch', 'raw-staged', 0, 1, "
                "'2026-01-01', '2026-01-01')",
                {"account": account, "fingerprint": "e" * 64},
            )
        connection.rollback()
    engine.dispose()


def test_0008_downgrade_refuses_generic_account(tmp_path: Path) -> None:
    engine, config = _database_at_0007(tmp_path)
    command.upgrade(config, "20260813_0008")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO accounts (id, name, default_currency, is_active, created_at, updated_at) "
            "VALUES ('generic', 'Generic', 'EUR', 1, '2026-01-01', '2026-01-01')"
        )
    with pytest.raises(RuntimeError, match="generic accounts"):
        command.downgrade(config, "20260812_0007")
    engine.dispose()


def test_clean_legacy_upgrade_can_downgrade(tmp_path: Path) -> None:
    engine, config = _database_at_0007(tmp_path)
    command.upgrade(config, "20260813_0008")
    command.downgrade(config, "20260812_0007")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT count(*) FROM source_accounts").scalar_one() == 6
        assert connection.exec_driver_sql("PRAGMA foreign_key_check").all() == []
        assert connection.exec_driver_sql("PRAGMA integrity_check").scalar_one() == "ok"
    engine.dispose()


def _database_at_0007(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'migration.sqlite3'}")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    config = Config(Path(__file__).parents[1] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", str(engine.url))
    command.upgrade(config, "20260812_0007")
    return engine, config
