from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from backend.app.database.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connection = config.attributes.get("connection")
    if connection is not None:
        config.attributes["fresh_install"] = not _has_alembic_version(connection)
        context.configure(
            connection=connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as created_connection:
        config.attributes["fresh_install"] = not _has_alembic_version(created_connection)
        created_connection.commit()
        context.configure(
            connection=created_connection, target_metadata=target_metadata, render_as_batch=True
        )
        with context.begin_transaction():
            context.run_migrations()


def _has_alembic_version(connection) -> bool:
    return bool(
        connection.exec_driver_sql(
            "SELECT 1 FROM sqlite_schema WHERE type = 'table' AND name = 'alembic_version'"
        ).scalar()
    )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
