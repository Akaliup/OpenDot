"""Initial SQLite schema frozen at the first CommerceOps release."""

from alembic import op
from sqlalchemy import inspect

revision = "0001_workspace"
down_revision = None
branch_labels = None
depends_on = None


SCHEMA = {
    "sop_documents": """
CREATE TABLE sop_documents (
    id VARCHAR(80) NOT NULL,
    title VARCHAR(200) NOT NULL,
    version VARCHAR(40) NOT NULL,
    body_markdown TEXT NOT NULL,
    source_sha256 VARCHAR(64) NOT NULL,
    PRIMARY KEY (id)
)
""",
    "stores": """
CREATE TABLE stores (
    id VARCHAR(200) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    code VARCHAR(64) NOT NULL,
    name VARCHAR(200) NOT NULL,
    marketplace VARCHAR(64) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    timezone VARCHAR(64) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_store_workspace_code UNIQUE (workspace_id, code)
)
""",
    "suppliers": """
CREATE TABLE suppliers (
    id VARCHAR(200) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    code VARCHAR(64) NOT NULL,
    name VARCHAR(200) NOT NULL,
    country VARCHAR(8) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_supplier_workspace_code UNIQUE (workspace_id, code)
)
""",
    "action_drafts": """
CREATE TABLE action_drafts (
    id VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    action_type VARCHAR(40) NOT NULL,
    status VARCHAR(16) NOT NULL,
    idempotency_key VARCHAR(200) NOT NULL,
    store_id VARCHAR(200) NOT NULL,
    formula_version VARCHAR(40) NOT NULL,
    payload_json TEXT NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    created_by VARCHAR(120) NOT NULL,
    approval_id VARCHAR(64),
    executed_at VARCHAR(40),
    execution_ref VARCHAR(64),
    PRIMARY KEY (id),
    CONSTRAINT ck_action_draft_status CHECK (status IN ('draft', 'executed', 'rejected')),
    CONSTRAINT ck_action_draft_type CHECK (action_type IN ('ad_budget_adjustment', 'purchase_order', 'competitor_response')),
    UNIQUE (idempotency_key),
    FOREIGN KEY(store_id) REFERENCES stores (id)
)
""",
    "products": """
CREATE TABLE products (
    id VARCHAR(240) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    store_id VARCHAR(200) NOT NULL,
    sku VARCHAR(64) NOT NULL,
    asin VARCHAR(32) NOT NULL,
    title VARCHAR(300) NOT NULL,
    list_price VARCHAR(40) NOT NULL,
    unit_cogs VARCHAR(40) NOT NULL,
    bullet_points TEXT NOT NULL,
    currency VARCHAR(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_product_store_sku UNIQUE (store_id, sku),
    FOREIGN KEY(store_id) REFERENCES stores (id)
)
""",
    "supplier_quotes": """
CREATE TABLE supplier_quotes (
    id VARCHAR(240) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    supplier_id VARCHAR(200) NOT NULL,
    sku VARCHAR(64) NOT NULL,
    tier_min_qty INTEGER NOT NULL,
    unit_price VARCHAR(40) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    moq INTEGER NOT NULL,
    lead_time_days INTEGER NOT NULL,
    order_multiple INTEGER NOT NULL,
    freight_per_unit VARCHAR(40) NOT NULL,
    duty_rate VARCHAR(40) NOT NULL,
    on_time_rate VARCHAR(40),
    on_time_sample_size INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_supplier_quote_tier UNIQUE (workspace_id, supplier_id, sku, tier_min_qty),
    FOREIGN KEY(supplier_id) REFERENCES suppliers (id)
)
""",
    "ad_campaigns": """
CREATE TABLE ad_campaigns (
    id VARCHAR(160) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    store_id VARCHAR(200) NOT NULL,
    product_id VARCHAR(240),
    external_id VARCHAR(80) NOT NULL,
    name VARCHAR(200) NOT NULL,
    daily_budget VARCHAR(40) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_campaign UNIQUE (store_id, external_id),
    FOREIGN KEY(store_id) REFERENCES stores (id),
    FOREIGN KEY(product_id) REFERENCES products (id)
)
""",
    "approval_records": """
CREATE TABLE approval_records (
    id VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    draft_id VARCHAR(64) NOT NULL,
    approver VARCHAR(120) NOT NULL,
    note TEXT NOT NULL,
    decision VARCHAR(16) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT ck_approval_decision CHECK (decision IN ('approved', 'rejected')),
    UNIQUE (draft_id),
    FOREIGN KEY(draft_id) REFERENCES action_drafts (id)
)
""",
    "competitor_responses": """
CREATE TABLE competitor_responses (
    id VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    draft_id VARCHAR(64) NOT NULL,
    store_id VARCHAR(200) NOT NULL,
    sku VARCHAR(64) NOT NULL,
    plan_json TEXT NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (draft_id),
    FOREIGN KEY(draft_id) REFERENCES action_drafts (id),
    FOREIGN KEY(store_id) REFERENCES stores (id)
)
""",
    "competitor_snapshots": """
CREATE TABLE competitor_snapshots (
    id VARCHAR(240) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    store_id VARCHAR(200) NOT NULL,
    product_id VARCHAR(240) NOT NULL,
    competitor_asin VARCHAR(32) NOT NULL,
    competitor_title VARCHAR(300) NOT NULL,
    captured_at VARCHAR(40) NOT NULL,
    source VARCHAR(80) NOT NULL,
    collection_method VARCHAR(32) NOT NULL,
    price VARCHAR(40) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    bsr INTEGER,
    rating VARCHAR(40),
    review_count INTEGER NOT NULL,
    negative_review_hits INTEGER NOT NULL,
    negative_keywords TEXT NOT NULL,
    bullet_points TEXT NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_competitor_snapshot UNIQUE (product_id, competitor_asin, captured_at),
    CONSTRAINT ck_competitor_collection_method CHECK (collection_method IN ('demo_seed', 'manual_import', 'licensed_feed')),
    FOREIGN KEY(store_id) REFERENCES stores (id),
    FOREIGN KEY(product_id) REFERENCES products (id)
)
""",
    "inventory_snapshots": """
CREATE TABLE inventory_snapshots (
    id VARCHAR(200) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    store_id VARCHAR(200) NOT NULL,
    product_id VARCHAR(240) NOT NULL,
    snapshot_date DATE NOT NULL,
    on_hand INTEGER NOT NULL,
    reserved INTEGER NOT NULL,
    inbound_qty INTEGER NOT NULL,
    inbound_eta DATE,
    safety_stock INTEGER NOT NULL,
    target_cover_days INTEGER NOT NULL,
    planning_lead_time_days INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_inventory_snapshot UNIQUE (product_id, snapshot_date),
    FOREIGN KEY(store_id) REFERENCES stores (id),
    FOREIGN KEY(product_id) REFERENCES products (id)
)
""",
    "orders": """
CREATE TABLE orders (
    id VARCHAR(220) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    store_id VARCHAR(200) NOT NULL,
    product_id VARCHAR(240) NOT NULL,
    external_order_id VARCHAR(80) NOT NULL,
    line_id VARCHAR(40) NOT NULL,
    ordered_at DATE NOT NULL,
    quantity INTEGER NOT NULL,
    gross_revenue VARCHAR(40) NOT NULL,
    discount VARCHAR(40) NOT NULL,
    unit_cogs VARCHAR(40) NOT NULL,
    platform_fee VARCHAR(40) NOT NULL,
    shipping_fee VARCHAR(40) NOT NULL,
    other_fee VARCHAR(40) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_order_line UNIQUE (store_id, external_order_id, line_id),
    FOREIGN KEY(store_id) REFERENCES stores (id),
    FOREIGN KEY(product_id) REFERENCES products (id)
)
""",
    "purchase_orders": """
CREATE TABLE purchase_orders (
    id VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    draft_id VARCHAR(64) NOT NULL,
    store_id VARCHAR(200) NOT NULL,
    supplier_id VARCHAR(200) NOT NULL,
    sku VARCHAR(64) NOT NULL,
    quantity INTEGER NOT NULL,
    unit_landed_cost VARCHAR(40) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    status VARCHAR(32) NOT NULL,
    sent_to_supplier INTEGER NOT NULL,
    simulation_note VARCHAR(200) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (draft_id),
    FOREIGN KEY(draft_id) REFERENCES action_drafts (id),
    FOREIGN KEY(store_id) REFERENCES stores (id),
    FOREIGN KEY(supplier_id) REFERENCES suppliers (id)
)
""",
    "refunds": """
CREATE TABLE refunds (
    id VARCHAR(200) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    store_id VARCHAR(200) NOT NULL,
    product_id VARCHAR(240) NOT NULL,
    external_refund_id VARCHAR(80) NOT NULL,
    order_external_id VARCHAR(80) NOT NULL,
    refunded_at DATE NOT NULL,
    quantity INTEGER NOT NULL,
    amount VARCHAR(40) NOT NULL,
    recovered_cogs VARCHAR(40) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_refund UNIQUE (store_id, external_refund_id),
    FOREIGN KEY(store_id) REFERENCES stores (id),
    FOREIGN KEY(product_id) REFERENCES products (id)
)
""",
    "writeback_audit_logs": """
CREATE TABLE writeback_audit_logs (
    id INTEGER NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    draft_id VARCHAR(64) NOT NULL,
    event VARCHAR(40) NOT NULL,
    actor VARCHAR(120) NOT NULL,
    payload_hash VARCHAR(64) NOT NULL,
    detail_json TEXT NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    FOREIGN KEY(draft_id) REFERENCES action_drafts (id)
)
""",
    "ad_budget_revisions": """
CREATE TABLE ad_budget_revisions (
    id VARCHAR(64) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    draft_id VARCHAR(64) NOT NULL,
    campaign_id VARCHAR(160) NOT NULL,
    previous_daily_budget VARCHAR(40) NOT NULL,
    new_daily_budget VARCHAR(40) NOT NULL,
    created_at VARCHAR(40) NOT NULL,
    PRIMARY KEY (id),
    UNIQUE (draft_id),
    FOREIGN KEY(draft_id) REFERENCES action_drafts (id),
    FOREIGN KEY(campaign_id) REFERENCES ad_campaigns (id)
)
""",
    "ad_metric_days": """
CREATE TABLE ad_metric_days (
    id VARCHAR(200) NOT NULL,
    workspace_id VARCHAR(128) NOT NULL,
    campaign_id VARCHAR(160) NOT NULL,
    metric_date DATE NOT NULL,
    impressions INTEGER NOT NULL,
    clicks INTEGER NOT NULL,
    spend VARCHAR(40) NOT NULL,
    attributed_sales VARCHAR(40) NOT NULL,
    attributed_orders INTEGER NOT NULL,
    PRIMARY KEY (id),
    CONSTRAINT uq_ad_metric_day UNIQUE (campaign_id, metric_date),
    FOREIGN KEY(campaign_id) REFERENCES ad_campaigns (id)
)
""",
}

INDEXES = (
    ("stores", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_stores_workspace_id ON stores (workspace_id)"),
    ("suppliers", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_suppliers_workspace_id ON suppliers (workspace_id)"),
    ("action_drafts", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_action_drafts_workspace_id ON action_drafts (workspace_id)"),
    ("products", "store_id", "CREATE INDEX IF NOT EXISTS ix_products_store_id ON products (store_id)"),
    ("products", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_products_workspace_id ON products (workspace_id)"),
    ("supplier_quotes", "sku", "CREATE INDEX IF NOT EXISTS ix_supplier_quotes_sku ON supplier_quotes (sku)"),
    ("supplier_quotes", "supplier_id", "CREATE INDEX IF NOT EXISTS ix_supplier_quotes_supplier_id ON supplier_quotes (supplier_id)"),
    ("supplier_quotes", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_supplier_quotes_workspace_id ON supplier_quotes (workspace_id)"),
    ("ad_campaigns", "store_id", "CREATE INDEX IF NOT EXISTS ix_ad_campaigns_store_id ON ad_campaigns (store_id)"),
    ("ad_campaigns", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_ad_campaigns_workspace_id ON ad_campaigns (workspace_id)"),
    ("approval_records", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_approval_records_workspace_id ON approval_records (workspace_id)"),
    ("competitor_responses", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_competitor_responses_workspace_id ON competitor_responses (workspace_id)"),
    ("competitor_snapshots", "product_id", "CREATE INDEX IF NOT EXISTS ix_competitor_snapshots_product_id ON competitor_snapshots (product_id)"),
    ("competitor_snapshots", "store_id", "CREATE INDEX IF NOT EXISTS ix_competitor_snapshots_store_id ON competitor_snapshots (store_id)"),
    ("competitor_snapshots", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_competitor_snapshots_workspace_id ON competitor_snapshots (workspace_id)"),
    ("inventory_snapshots", "product_id", "CREATE INDEX IF NOT EXISTS ix_inventory_snapshots_product_id ON inventory_snapshots (product_id)"),
    ("inventory_snapshots", "snapshot_date", "CREATE INDEX IF NOT EXISTS ix_inventory_snapshots_snapshot_date ON inventory_snapshots (snapshot_date)"),
    ("inventory_snapshots", "store_id", "CREATE INDEX IF NOT EXISTS ix_inventory_snapshots_store_id ON inventory_snapshots (store_id)"),
    ("inventory_snapshots", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_inventory_snapshots_workspace_id ON inventory_snapshots (workspace_id)"),
    ("orders", "ordered_at", "CREATE INDEX IF NOT EXISTS ix_orders_ordered_at ON orders (ordered_at)"),
    ("orders", "product_id", "CREATE INDEX IF NOT EXISTS ix_orders_product_id ON orders (product_id)"),
    ("orders", "store_id", "CREATE INDEX IF NOT EXISTS ix_orders_store_id ON orders (store_id)"),
    ("orders", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_orders_workspace_id ON orders (workspace_id)"),
    ("purchase_orders", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_purchase_orders_workspace_id ON purchase_orders (workspace_id)"),
    ("refunds", "refunded_at", "CREATE INDEX IF NOT EXISTS ix_refunds_refunded_at ON refunds (refunded_at)"),
    ("refunds", "store_id", "CREATE INDEX IF NOT EXISTS ix_refunds_store_id ON refunds (store_id)"),
    ("refunds", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_refunds_workspace_id ON refunds (workspace_id)"),
    ("writeback_audit_logs", "draft_id", "CREATE INDEX IF NOT EXISTS ix_writeback_audit_logs_draft_id ON writeback_audit_logs (draft_id)"),
    ("writeback_audit_logs", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_writeback_audit_logs_workspace_id ON writeback_audit_logs (workspace_id)"),
    ("ad_budget_revisions", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_ad_budget_revisions_workspace_id ON ad_budget_revisions (workspace_id)"),
    ("ad_metric_days", "campaign_id", "CREATE INDEX IF NOT EXISTS ix_ad_metric_days_campaign_id ON ad_metric_days (campaign_id)"),
    ("ad_metric_days", "metric_date", "CREATE INDEX IF NOT EXISTS ix_ad_metric_days_metric_date ON ad_metric_days (metric_date)"),
    ("ad_metric_days", "workspace_id", "CREATE INDEX IF NOT EXISTS ix_ad_metric_days_workspace_id ON ad_metric_days (workspace_id)"),
)


def upgrade() -> None:
    conn = op.get_bind()
    existing = set(inspect(conn).get_table_names())
    for name, ddl in SCHEMA.items():
        if name not in existing:
            conn.exec_driver_sql(ddl)
    for table, _, ddl in INDEXES:
        if table not in existing:
            conn.exec_driver_sql(ddl)


def downgrade() -> None:
    raise RuntimeError("CommerceOps migrations preserve workspace history")
