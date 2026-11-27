"""Commerce tables. Money columns use ExactNumeric, not SQLite REAL."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from commerceops.types import ExactNumeric


class Base(DeclarativeBase):
    pass


class Store(Base):
    __tablename__ = "stores"
    __table_args__ = (UniqueConstraint("workspace_id", "code", name="uq_store_workspace_code"),)

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (UniqueConstraint("store_id", "sku", name="uq_product_store_sku"),)

    id: Mapped[str] = mapped_column(String(240), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    asin: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    list_price: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    unit_cogs: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    bullet_points: Mapped[str] = mapped_column(Text, nullable=False, default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint("store_id", "external_order_id", "line_id", name="uq_order_line"),
    )

    id: Mapped[str] = mapped_column(String(220), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    external_order_id: Mapped[str] = mapped_column(String(80), nullable=False)
    line_id: Mapped[str] = mapped_column(String(40), nullable=False)
    ordered_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    gross_revenue: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    discount: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    unit_cogs: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    platform_fee: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    shipping_fee: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    other_fee: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class Refund(Base):
    __tablename__ = "refunds"
    __table_args__ = (UniqueConstraint("store_id", "external_refund_id", name="uq_refund"),)

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False)
    external_refund_id: Mapped[str] = mapped_column(String(80), nullable=False)
    order_external_id: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    refunded_at: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    amount: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    recovered_cogs: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class AdCampaign(Base):
    __tablename__ = "ad_campaigns"
    __table_args__ = (UniqueConstraint("store_id", "external_id", name="uq_campaign"),)

    id: Mapped[str] = mapped_column(String(160), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    product_id: Mapped[str | None] = mapped_column(ForeignKey("products.id"), nullable=True)
    external_id: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    daily_budget: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class AdMetricDay(Base):
    __tablename__ = "ad_metric_days"
    __table_args__ = (UniqueConstraint("campaign_id", "metric_date", name="uq_ad_metric_day"),)

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("ad_campaigns.id"), nullable=False, index=True)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    impressions: Mapped[int] = mapped_column(Integer, nullable=False)
    clicks: Mapped[int] = mapped_column(Integer, nullable=False)
    spend: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    attributed_sales: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    attributed_orders: Mapped[int] = mapped_column(Integer, nullable=False)


class InventorySnapshot(Base):
    __tablename__ = "inventory_snapshots"
    __table_args__ = (UniqueConstraint("product_id", "snapshot_date", name="uq_inventory_snapshot"),)

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    on_hand: Mapped[int] = mapped_column(Integer, nullable=False)
    reserved: Mapped[int] = mapped_column(Integer, nullable=False)
    inbound_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    inbound_eta: Mapped[date | None] = mapped_column(Date, nullable=True)
    safety_stock: Mapped[int] = mapped_column(Integer, nullable=False)
    target_cover_days: Mapped[int] = mapped_column(Integer, nullable=False)
    planning_lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)


class Supplier(Base):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("workspace_id", "code", name="uq_supplier_workspace_code"),)

    id: Mapped[str] = mapped_column(String(200), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    country: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False)


class SupplierQuote(Base):
    __tablename__ = "supplier_quotes"
    __table_args__ = (
        UniqueConstraint("workspace_id", "supplier_id", "sku", "tier_min_qty", name="uq_supplier_quote_tier"),
    )

    id: Mapped[str] = mapped_column(String(240), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), nullable=False, index=True)
    sku: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    tier_min_qty: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    moq: Mapped[int] = mapped_column(Integer, nullable=False)
    lead_time_days: Mapped[int] = mapped_column(Integer, nullable=False)
    order_multiple: Mapped[int] = mapped_column(Integer, nullable=False)
    freight_per_unit: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    duty_rate: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    on_time_rate: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    on_time_sample_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class CompetitorSnapshot(Base):
    __tablename__ = "competitor_snapshots"
    __table_args__ = (
        UniqueConstraint("product_id", "competitor_asin", "captured_at", name="uq_competitor_snapshot"),
        CheckConstraint(
            "collection_method IN ('demo_seed', 'manual_import', 'licensed_feed')",
            name="ck_competitor_collection_method",
        ),
    )

    id: Mapped[str] = mapped_column(String(240), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), nullable=False, index=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("products.id"), nullable=False, index=True)
    competitor_asin: Mapped[str] = mapped_column(String(32), nullable=False)
    competitor_title: Mapped[str] = mapped_column(String(300), nullable=False)
    captured_at: Mapped[str] = mapped_column(String(40), nullable=False)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    collection_method: Mapped[str] = mapped_column(String(32), nullable=False)
    price: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    bsr: Mapped[int | None] = mapped_column(Integer, nullable=True)
    rating: Mapped[Decimal | None] = mapped_column(ExactNumeric(), nullable=True)
    review_count: Mapped[int] = mapped_column(Integer, nullable=False)
    negative_review_hits: Mapped[int] = mapped_column(Integer, nullable=False)
    negative_keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    bullet_points: Mapped[str] = mapped_column(Text, nullable=False, default="")


class SopDocument(Base):
    __tablename__ = "sop_documents"

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    version: Mapped[str] = mapped_column(String(40), nullable=False)
    body_markdown: Mapped[str] = mapped_column(Text, nullable=False)
    source_sha256: Mapped[str] = mapped_column(String(64), nullable=False)


class ActionDraft(Base):
    __tablename__ = "action_drafts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'executed', 'rejected')",
            name="ck_action_draft_status",
        ),
        CheckConstraint(
            "action_type IN ('ad_budget_adjustment', 'purchase_order', 'competitor_response')",
            name="ck_action_draft_type",
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    idempotency_key: Mapped[str] = mapped_column(String(200), nullable=False, unique=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), nullable=False)
    formula_version: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_json: Mapped[str] = mapped_column(Text, nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[str] = mapped_column(String(120), nullable=False)
    approval_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    executed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    execution_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)


class ApprovalRecord(Base):
    __tablename__ = "approval_records"
    __table_args__ = (
        CheckConstraint("decision IN ('approved', 'rejected')", name="ck_approval_decision"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("action_drafts.id"), nullable=False, unique=True)
    approver: Mapped[str] = mapped_column(String(120), nullable=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class WritebackAuditLog(Base):
    __tablename__ = "writeback_audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("action_drafts.id"), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    actor: Mapped[str] = mapped_column(String(120), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    detail_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class PurchaseOrder(Base):
    __tablename__ = "purchase_orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("action_drafts.id"), nullable=False, unique=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), nullable=False)
    supplier_id: Mapped[str] = mapped_column(ForeignKey("suppliers.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_landed_cost: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="simulated_open")
    sent_to_supplier: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    simulation_note: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class AdBudgetRevision(Base):
    __tablename__ = "ad_budget_revisions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("action_drafts.id"), nullable=False, unique=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("ad_campaigns.id"), nullable=False)
    previous_daily_budget: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    new_daily_budget: Mapped[Decimal] = mapped_column(ExactNumeric(), nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)


class CompetitorResponse(Base):
    __tablename__ = "competitor_responses"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    draft_id: Mapped[str] = mapped_column(ForeignKey("action_drafts.id"), nullable=False, unique=True)
    store_id: Mapped[str] = mapped_column(ForeignKey("stores.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(64), nullable=False)
    plan_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[str] = mapped_column(String(40), nullable=False)
