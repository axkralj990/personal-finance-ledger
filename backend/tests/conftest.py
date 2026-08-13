from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.config import Settings
from backend.app.database.models import Account
from backend.app.database.session import Database
from backend.app.main import create_app


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        data_dir=tmp_path,
        database_url=f"sqlite:///{tmp_path / 'test.sqlite3'}",
        frontend_dist_path=tmp_path / "missing-dist",
        max_file_rows=100,
    )


@pytest.fixture
def database(settings: Settings) -> Iterator[Database]:
    database = Database(settings.resolved_database_url)
    database.migrate()
    yield database
    database.dispose()


@pytest.fixture
def account(database: Database) -> Account:
    with database.session() as session:
        account = Account(
            name="Synthetic checking",
            default_currency="EUR",
        )
        session.add(account)
        session.commit()
        session.expunge(account)
        return account


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client
