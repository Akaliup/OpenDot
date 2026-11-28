import sqlite3

import pytest
from sqlalchemy import CheckConstraint, UniqueConstraint, inspect

from commerceops.db import _migrate, init_db
from commerceops.models import Base


def test_empty_schema_matches_models_and_second_upgrade_is_idle(database_url):
    engine = init_db(database_url)
    _migrate(database_url)
    schema = inspect(engine)
    for table in Base.metadata.sorted_tables:
        actual = {c["name"]: c for c in schema.get_columns(table.name)}
        assert set(actual) == set(table.columns.keys())
        if "workspace_id" in table.columns:
            assert not actual["workspace_id"]["nullable"]
        assert {i["name"] for i in schema.get_indexes(table.name)} == {i.name for i in table.indexes}
        assert schema.get_pk_constraint(table.name)["constrained_columns"] == list(table.primary_key.columns.keys())
        assert {tuple(fk["constrained_columns"]) for fk in schema.get_foreign_keys(table.name)} == {
            tuple(fk.columns.keys()) for fk in table.foreign_key_constraints}
        assert {tuple(u["column_names"]) for u in schema.get_unique_constraints(table.name)} == {
            tuple(c.columns.keys()) for c in table.constraints if isinstance(c, UniqueConstraint)}
        assert {c["sqltext"] for c in schema.get_check_constraints(table.name)} == {
            str(c.sqltext) for c in table.constraints if isinstance(c, CheckConstraint)}


def test_stamped_nullable_database_keeps_rows_indexes_and_audit_trigger(tmp_path):
    path = tmp_path / "legacy.db"
    url = f"sqlite:///{path}"
    _migrate(url)
    with sqlite3.connect(path) as db:
        db.executescript("""
            UPDATE alembic_version SET version_num='0001_workspace';
            DROP TABLE writeback_audit_logs;
            CREATE TABLE writeback_audit_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,
                workspace_id VARCHAR(128), event TEXT);
            CREATE INDEX audit_expr ON writeback_audit_logs(lower(event)) WHERE event IS NOT NULL;
            INSERT INTO writeback_audit_logs VALUES (8,NULL,'approved'),(9,'owned','saved');
            CREATE TRIGGER immutable BEFORE UPDATE ON writeback_audit_logs
              BEGIN SELECT RAISE(ABORT,'immutable'); END;
        """)
        db.executescript("""
            CREATE TABLE legacy_evidence(id TEXT PRIMARY KEY);
            INSERT INTO legacy_evidence VALUES ('order-1'), ('approval-1');
        """)
        for table, identifier in (("orders", "order-1"), ("approval_records", "approval-1")):
            db.execute(f'DROP TABLE "{table}"')
            db.execute(f'CREATE TABLE "{table}"(id TEXT PRIMARY KEY REFERENCES legacy_evidence(id), amount TEXT)')
            db.execute(f'INSERT INTO "{table}" VALUES (?,?)', (identifier, "10.00"))
    _migrate(url)
    _migrate(url)
    with sqlite3.connect(path) as db:
        assert db.execute("SELECT * FROM writeback_audit_logs ORDER BY id").fetchall() == [
            (8, "ws-legacy", "approved"), (9, "owned", "saved")]
        for table, identifier in (("orders", "order-1"), ("approval_records", "approval-1")):
            assert db.execute(f'SELECT * FROM "{table}"').fetchall() == [(identifier, "10.00", "ws-legacy")]
            assert db.execute(f'PRAGMA foreign_key_list("{table}")').fetchone()[2] == "legacy_evidence"
        assert db.execute("SELECT sql FROM sqlite_master WHERE name='audit_expr'").fetchone()
        with pytest.raises(sqlite3.IntegrityError, match="NOT NULL"):
            db.execute("INSERT INTO writeback_audit_logs(event) VALUES ('invalid')")
        with pytest.raises(sqlite3.IntegrityError, match="immutable"):
            db.execute("UPDATE writeback_audit_logs SET event='changed'")
