from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import async_engine_from_config

from app.core.config import get_settings
from app.db.models import Base

config = context.config
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Run this conditional step only when `config.config_file_name is not None` is true.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


# Runs migrations offline; Alembic uses it to configure and execute database migrations.
def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    # Keep `context.begin_transaction()` active while this scoped operation is performed.
    with context.begin_transaction():
        context.run_migrations()


# Runs migrations online; Alembic uses it to configure and execute database migrations.
def run_migrations_online() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    from asyncio import run

    # Attaches the connection and executes Alembic migrations; Alembic uses it to configure and execute database migrations.
    def do_run_migrations(connection) -> None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        # Keep `context.begin_transaction()` active while this scoped operation is performed.
        with context.begin_transaction():
            context.run_migrations()

    # Runs migrations inside the configured connection; Alembic uses it to configure and execute database migrations.
    async def do_migrations() -> None:
        # Keep `connectable.connect()` active while this scoped operation is performed.
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
        await connectable.dispose()

    run(do_migrations())


# Choose the appropriate path based on whether `context.is_offline_mode()` is true.
if context.is_offline_mode():
    run_migrations_offline()
# Handle the alternate path after the preceding branch or loop does not produce a result.
else:
    run_migrations_online()
