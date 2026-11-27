"""Initial schema, plus workspace_id for a database created before Alembic."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from commerceops.context import LEGACY_WORKSPACE
from commerceops.models import Base

revision = "0001_workspace"
down_revision = None
branch_labels = None
depends_on = None

WORKSPACE_TABLES = (
    "stores",
    "products",
    "orders",
    "refunds",
    "ad_campaigns",
    "ad_metric_days",
    "inventory_snapshots",
    "suppliers",
    "supplier_quotes",
    "competitor_snapshots",
    "action_drafts",
    "approval_records",
    "writeback_audit_logs",
    "purchase_orders",
    "ad_budget_revisions",
    "competitor_responses",
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    existing = [table for table in WORKSPACE_TABLES if table in tables]
    if not existing:
        Base.metadata.create_all(bind)
        return
    Base.metadata.create_all(bind)
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())
    for table in WORKSPACE_TABLES:
        if table not in tables:
            continue
        columns = {column["name"] for column in inspector.get_columns(table)}
        if "workspace_id" in columns:
            continue
        op.add_column(table, sa.Column("workspace_id", sa.String(length=128), nullable=True))
        op.execute(
            sa.text(
                f"UPDATE {table} SET workspace_id = '{LEGACY_WORKSPACE}' WHERE workspace_id IS NULL"
            )
        )


def downgrade() -> None:
    raise RuntimeError("CommerceOps migrations do not drop workspace history")
