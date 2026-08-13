from collections.abc import Iterator
from pathlib import Path
from sqlite3 import Connection as SQLiteConnection

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker


class Database:
    def __init__(self, url: str) -> None:
        self.engine = create_engine(url, pool_pre_ping=True)
        if self.engine.dialect.name == "sqlite":
            event.listen(self.engine, "connect", _configure_sqlite)
        self.session_factory = sessionmaker(self.engine, expire_on_commit=False)

    def session(self) -> Session:
        return self.session_factory()

    def dependency(self) -> Iterator[Session]:
        with self.session() as session:
            try:
                yield session
            except Exception:
                session.rollback()
                raise

    def migrate(self) -> None:
        self._ensure_sqlite_parent()
        config_path = Path(__file__).parents[2] / "alembic.ini"
        config = Config(config_path)
        config.set_main_option("sqlalchemy.url", str(self.engine.url))

        with self.engine.connect() as connection:
            config.attributes["connection"] = connection
            if self.engine.dialect.name == "sqlite":
                connection.exec_driver_sql("PRAGMA journal_mode=WAL")
                connection.exec_driver_sql("PRAGMA foreign_keys=OFF")

            try:
                command.upgrade(config, "head")
                connection.commit()
                if self.engine.dialect.name != "sqlite":
                    return
                violations = connection.exec_driver_sql("PRAGMA foreign_key_check").all()
                if violations:
                    raise RuntimeError(f"Database foreign key check failed: {violations!r}")
                integrity = connection.exec_driver_sql("PRAGMA integrity_check").scalar_one()
                if integrity != "ok":
                    raise RuntimeError(f"Database integrity check failed: {integrity}")
            finally:
                connection.rollback()
                if self.engine.dialect.name == "sqlite":
                    connection.exec_driver_sql("PRAGMA foreign_keys=ON")

    def _ensure_sqlite_parent(self) -> None:
        if self.engine.dialect.name != "sqlite":
            return
        database_path = self.engine.url.database
        if database_path and database_path != ":memory:":
            Path(database_path).parent.mkdir(parents=True, exist_ok=True)

    def dispose(self) -> None:
        self.engine.dispose()


def _configure_sqlite(connection: SQLiteConnection, _record: object) -> None:
    cursor = connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()
