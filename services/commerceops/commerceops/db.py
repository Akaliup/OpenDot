"""SQLite-first engine. Postgres is a dialect change, not a second schema."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

from commerceops.config import get_settings

_ENGINES: dict[str, Engine] = {}
_FACTORIES: dict[str, sessionmaker[Session]] = {}

_IMMUTABLE_SQL = (
    """
    CREATE TRIGGER IF NOT EXISTS writeback_audit_logs_no_update
    BEFORE UPDATE ON writeback_audit_logs
    BEGIN
      SELECT RAISE(ABORT, 'audit log is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS writeback_audit_logs_no_delete
    BEFORE DELETE ON writeback_audit_logs
    BEGIN
      SELECT RAISE(ABORT, 'audit log is immutable');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS purchase_orders_insert_not_sent
    BEFORE INSERT ON purchase_orders
    WHEN NEW.sent_to_supplier != 0
    BEGIN
      SELECT RAISE(ABORT, 'purchase orders are simulated and cannot be marked sent');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS purchase_orders_update_not_sent
    BEFORE UPDATE OF sent_to_supplier ON purchase_orders
    WHEN NEW.sent_to_supplier != 0
    BEGIN
      SELECT RAISE(ABORT, 'purchase orders are simulated and cannot be marked sent');
    END
    """,
)


def _migrate(database_url: str) -> None:
    from alembic.config import Config
    from alembic import command

    ini = Path(__file__).resolve().parent / "alembic.ini"
    cfg = Config(str(ini))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")


def init_db(database_url: str) -> Engine:
    if database_url in _ENGINES:
        return _ENGINES[database_url]
    _migrate(database_url)
    kwargs: dict = {"poolclass": NullPool, "future": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    engine = create_engine(database_url, **kwargs)
    if database_url.startswith("sqlite"):

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _connection_record) -> None:  # type: ignore[no-untyped-def]
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    with engine.begin() as connection:
        for statement in _IMMUTABLE_SQL:
            connection.execute(text(statement))
    _ENGINES[database_url] = engine
    _FACTORIES[database_url] = sessionmaker(bind=engine, expire_on_commit=False, future=True)
    return engine


def session_factory_for(database_url: str | None = None) -> sessionmaker[Session]:
    url = database_url or get_settings().database_url
    init_db(url)
    return _FACTORIES[url]


@contextmanager
def session_scope(database_url: str | None = None) -> Iterator[Session]:
    session = session_factory_for(database_url)()
    try:
        yield session
    finally:
        session.close()
