"""Alembic environment. The URL is injected by commerceops.db."""

from __future__ import annotations

from sqlalchemy import engine_from_config, pool

from alembic import context

from commerceops.models import Base

config = context.config
target_metadata = Base.metadata


def run_migrations_online() -> None:
    section = dict(config.get_section(config.config_ini_section) or {})
    section["sqlalchemy.url"] = config.get_main_option("sqlalchemy.url")
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, render_as_batch=True)
        if connection.dialect.name == "sqlite":
            connection.exec_driver_sql("BEGIN IMMEDIATE")
        with context.begin_transaction():
            context.run_migrations()
        connection.commit()


run_migrations_online()
