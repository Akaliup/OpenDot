"""Tool names exposed to an agent. Import and direct execution are not tools."""

READ_TOOLS = (
    "commerceops_list_stores",
    "commerceops_profit_report",
    "commerceops_ads_diagnosis",
    "commerceops_inventory_risk",
    "commerceops_supplier_comparison",
    "commerceops_competitor_diff",
    "commerceops_search_sops",
)

DRAFT_TOOLS = (
    "commerceops_create_ad_budget_draft",
    "commerceops_create_purchase_order_draft",
    "commerceops_create_competitor_response_draft",
)

APPROVAL_TOOLS = ("commerceops_approve_and_execute_draft",)

ALL_TOOLS = READ_TOOLS + DRAFT_TOOLS + APPROVAL_TOOLS

FORBIDDEN_TOOLS = (
    "commerceops_execute_draft",
    "commerceops_import_orders",
    "commerceops_import_ad_metrics",
    "commerceops_update_campaign_budget",
    "commerceops_send_purchase_order",
)
