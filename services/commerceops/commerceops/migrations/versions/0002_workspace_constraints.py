"""Enforce workspace ownership, including databases already stamped 0001."""

from importlib import import_module
import re

from alembic import op
from sqlalchemy import inspect

initial = import_module("commerceops.migrations.versions.0001_workspace")
revision = "0002_workspace_constraints"
down_revision = "0001_workspace"
branch_labels = None
depends_on = None
LEGACY_WORKSPACE = "ws-legacy"


def _rebuild(conn, table, columns):
    # Keep original constraint declarations, expression/partial indexes and triggers.
    schema = conn.exec_driver_sql(
        "SELECT type, sql FROM sqlite_master WHERE tbl_name=? AND sql IS NOT NULL "
        "ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END", (table,)
    ).all()
    ddl = schema[0].sql
    body, changed = re.subn(
        r'(?i)([(,]\s*["`\[]?workspace_id["`\]]?\s+(?:VARCHAR(?:\(\d+\))?|TEXT))(?=[\s,)])',
        r'\1 NOT NULL', ddl[ddl.index("("):], count=1,
    )
    if not changed:
        raise RuntimeError(f"Unrecognized workspace_id declaration in {table}")
    sequence = None
    if "AUTOINCREMENT" in ddl.upper():
        sequence = conn.exec_driver_sql("SELECT seq FROM sqlite_sequence WHERE name=?", (table,)).scalar()
    temp = f"_upgrade_{table}"
    conn.exec_driver_sql(f'CREATE TABLE "{temp}" {body}')
    quote = conn.dialect.identifier_preparer.quote_identifier
    names = ", ".join(quote(col["name"]) for col in columns)
    values = ", ".join("COALESCE(workspace_id, ?)" if col["name"] == "workspace_id"
                       else quote(col["name"]) for col in columns)
    conn.exec_driver_sql(f'INSERT INTO "{temp}" ({names}) SELECT {values} FROM "{table}"',
                         (LEGACY_WORKSPACE,))
    conn.exec_driver_sql(f'DROP TABLE "{table}"')
    conn.exec_driver_sql(f'ALTER TABLE "{temp}" RENAME TO "{table}"')
    if sequence is not None:
        conn.exec_driver_sql("UPDATE sqlite_sequence SET seq=MAX(seq,?) WHERE name=?", (sequence, table))
    for obj in schema[1:]:
        conn.exec_driver_sql(obj.sql)


def upgrade() -> None:
    conn = op.get_bind()
    for table in initial.SCHEMA:
        if table == "sop_documents":  # Shared, versioned knowledge library.
            continue
        cols = inspect(conn).get_columns(table)
        workspace = next((col for col in cols if col["name"] == "workspace_id"), None)
        if workspace is None:
            conn.exec_driver_sql(f'ALTER TABLE "{table}" ADD COLUMN workspace_id VARCHAR(128)')
            cols = inspect(conn).get_columns(table)
        if workspace is None or workspace["nullable"]:
            _rebuild(conn, table, cols)
    for table, column, ddl in initial.INDEXES:
        if column in {col["name"] for col in inspect(conn).get_columns(table)}:
            conn.exec_driver_sql(ddl)


def downgrade() -> None:
    raise RuntimeError("CommerceOps migrations preserve workspace history")
