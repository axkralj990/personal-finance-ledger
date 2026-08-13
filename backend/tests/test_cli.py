import sqlite3
import sys
from pathlib import Path

import pytest

from backend.app import cli
from backend.app.cli import backup_database
from backend.app.config import Settings


def test_backup_verifies_copy_and_never_overwrites_existing_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    output = tmp_path / "backup.bkp"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE accounts (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO accounts VALUES ('account')")
    settings = Settings(
        database_url=f"sqlite:///{source}",
        data_dir=tmp_path,
    )

    backup_database(settings, output)

    with sqlite3.connect(output) as connection:
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("SELECT count(*) FROM accounts").fetchone() == (1,)
    original = output.read_bytes()
    with pytest.raises(SystemExit, match="already exists"):
        backup_database(settings, output)
    assert output.read_bytes() == original


def test_backup_rejects_invalid_source_without_leaving_destination(tmp_path: Path) -> None:
    source = tmp_path / "source.sqlite3"
    output = tmp_path / "backup.bkp"
    source.write_bytes(b"not sqlite")

    with pytest.raises(SystemExit, match="failed verification"):
        backup_database(
            Settings(
                database_url=f"sqlite:///{source}",
                data_dir=tmp_path,
            ),
            output,
        )

    assert not output.exists()


def test_backup_command_does_not_run_migrations(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.sqlite3"
    output = tmp_path / "backup.bkp"
    with sqlite3.connect(source) as connection:
        connection.execute("CREATE TABLE accounts (id TEXT PRIMARY KEY)")
    settings = Settings(
        database_url=f"sqlite:///{source}",
        data_dir=tmp_path,
    )
    monkeypatch.setattr(cli, "Settings", lambda: settings)
    monkeypatch.setattr(
        cli.Database,
        "migrate",
        lambda _database: pytest.fail("backup must branch before Database.migrate"),
    )
    monkeypatch.setattr(sys, "argv", ["personal-finance", "backup", "--output", str(output)])

    cli.main()

    assert output.is_file()
