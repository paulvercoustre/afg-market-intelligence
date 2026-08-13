import os
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from sqlalchemy import engine_from_config, pool

load_dotenv()

config = context.config

if config.config_file_name is not None:
    # disable_existing_loggers=False: fileConfig()'s default (True) silently
    # disables every logger not explicitly listed in alembic.ini's [loggers]
    # section (only root/sqlalchemy/alembic are). Harmless when alembic runs
    # as its own CLI process, but when migrations run programmatically inside
    # a longer-lived process -- e.g. a test session that also calls
    # etl.run.main() -- this permanently silences that process's own loggers
    # (etl.run, etl.fetch, ...) for the rest of its lifetime.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# Override sqlalchemy.url from environment
database_url = os.environ.get("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

target_metadata = None


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
