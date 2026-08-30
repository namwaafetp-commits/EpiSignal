"""Alembic environment for the EpiSignal schema.

Offline mode renders SQL from a placeholder URL so that generating or reviewing
migrations never reads credentials or contacts a database. Online mode reads the
connection string from the validated backend settings and never logs it.
"""

from logging.config import fileConfig

import episignal_backend.models  # noqa: F401
from alembic import context
from episignal_backend.db.base import Base
from sqlalchemy import engine_from_config, pool

# The placeholder only selects the PostgreSQL dialect for offline rendering.
OFFLINE_URL = "postgresql+psycopg://offline:offline@localhost/offline"

config = context.config

if config.config_file_name is not None and config.get_section("loggers"):
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=OFFLINE_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    from episignal_backend.config import get_settings

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = get_settings().sqlalchemy_database_url

    connectable = engine_from_config(
        section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
        hide_parameters=True,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
