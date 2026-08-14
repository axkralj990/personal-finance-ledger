from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
from sqlalchemy.exc import IntegrityError


def test_populated_upgrade_derives_retired_history_and_limits_candidates(
    tmp_path: Path,
) -> None:
    engine = create_engine(f"sqlite:///{tmp_path / 'candidate-migration.sqlite3'}")
    config = Config(Path(__file__).parents[1] / "alembic.ini")
    config.set_main_option("sqlalchemy.url", str(engine.url))
    command.upgrade(config, "20260813_0008")
    with engine.begin() as connection:
        for model_id, created_at, is_active in (
            ("older", "2026-01-01", 0),
            ("previous", "2026-02-01", 0),
            ("active", "2026-03-01", 1),
        ):
            connection.exec_driver_sql(
                "INSERT INTO model_versions "
                "(id, name, artifact_path, checksum, training_metadata, taxonomy_version, "
                "is_active, created_at, activated_at) VALUES "
                "(:id, :id, :path, :checksum, '{}', 'active-taxonomy-v1', "
                ":active, :created, NULL)",
                {
                    "id": model_id,
                    "path": f"models/{model_id}.joblib",
                    "checksum": model_id.ljust(64, "0"),
                    "active": is_active,
                    "created": created_at,
                },
            )

    command.upgrade(config, "20260814_0009")

    assert "retired_at" in {
        column["name"] for column in inspect(engine).get_columns("model_versions")
    }
    with engine.begin() as connection:
        rows = {
            row.id: row
            for row in connection.exec_driver_sql(
                "SELECT id, activated_at, retired_at FROM model_versions"
            )
        }
        assert rows["older"].activated_at is not None
        assert rows["older"].retired_at is not None
        assert rows["previous"].activated_at is not None
        assert rows["previous"].retired_at is None
        assert rows["active"].activated_at is not None
        connection.exec_driver_sql(
            "INSERT INTO model_versions "
            "(id, name, artifact_path, checksum, training_metadata, taxonomy_version, "
            "is_active, created_at, activated_at, retired_at) VALUES "
            "('candidate-1', 'candidate-1', 'models/candidate-1.joblib', :checksum, '{}', "
            "'active-taxonomy-v1', 0, '2026-04-01', NULL, NULL)",
            {"checksum": "c" * 64},
        )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO model_versions "
            "(id, name, artifact_path, checksum, training_metadata, taxonomy_version, "
            "is_active, created_at, activated_at, retired_at) VALUES "
            "('candidate-2', 'candidate-2', 'models/candidate-2.joblib', :checksum, '{}', "
            "'active-taxonomy-v1', 0, '2026-04-02', NULL, NULL)",
            {"checksum": "d" * 64},
        )

    command.downgrade(config, "20260813_0008")
    assert "retired_at" not in {
        column["name"] for column in inspect(engine).get_columns("model_versions")
    }
    engine.dispose()
