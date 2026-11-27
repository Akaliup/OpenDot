"""Machine-readable formula catalog. Engines remain the implementation."""

from __future__ import annotations

from commerceops.engines.ads import FORMULA_VERSION as ADS_VERSION
from commerceops.engines.competitor import FORMULA_VERSION as COMPETITOR_VERSION
from commerceops.engines.inventory import FORMULA_VERSION as INVENTORY_VERSION
from commerceops.engines.price_sim import FORMULA_VERSION as PRICE_SIM_VERSION
from commerceops.engines.profit import FORMULA_VERSION as PROFIT_VERSION
from commerceops.engines.suppliers import FORMULA_VERSION as SUPPLIER_VERSION
from commerceops.engines.suppliers import WEIGHT_NOTE
from commerceops.sop.retrieval import FORMULA_VERSION as SOP_VERSION

FORMULA_VERSIONS = {
    "profit": PROFIT_VERSION,
    "ads": ADS_VERSION,
    "inventory": INVENTORY_VERSION,
    "supplier": SUPPLIER_VERSION,
    "competitor": COMPETITOR_VERSION,
    "price_sim": PRICE_SIM_VERSION,
    "sop": SOP_VERSION,
}

FORMULAS = {
    PROFIT_VERSION: {
        "net_sales": "revenue - discounts - refunds",
        "net_cogs": "cogs - recovered_cogs",
        "net_profit": "net_sales - net_cogs - platform_fees - shipping_fees - ad_spend - other_fees",
        "margin": "net_profit / net_sales when net_sales != 0, else null with status zero_net_sales",
        "ad_spend_source": "ad_metric_days for the store and window; order lines have no ad amount",
        "bridge": "sum of signed component deltas equals current net profit minus previous net profit",
    },
    ADS_VERSION: {
        "acos": "spend / attributed_sales, null status zero_attributed_sales when sales are 0",
        "roas": "attributed_sales / spend, null status zero_spend when spend is 0",
        "tacos": "spend / supplied sales denominator, null status zero_tacos_sales when that base is 0",
        "ctr": "clicks / impressions, null status zero_impressions when impressions are 0",
        "cpc": "spend / clicks, null status zero_clicks when clicks are 0",
        "cvr": "attributed_orders / clicks, null status zero_clicks when clicks are 0",
        "cpa": "spend / attributed_orders, null status zero_orders when orders are 0",
        "budget_ladder": "ACOS >= 0.80 -> 0.50; ACOS >= 0.40 -> 0.70; else spend-up CVR-down -> 0.80; else no cut",
    },
    INVENTORY_VERSION: {
        "available": "max(on_hand - reserved, 0); reserved > on_hand is oversold",
        "average_daily_sales": "units ordered in the lookback / lookback_days; refunds are not removed",
        "days_of_cover": "available / average_daily_sales, or null status undefined_no_velocity when velocity is 0",
        "reorder_point": "average_daily_sales * lead_time_days + safety_stock, null when velocity is 0",
        "suggested_order_qty": "ceiling of average_daily_sales * (lead_time + target_cover) + safety_stock - available - inbound",
    },
    SUPPLIER_VERSION: {
        "landed_unit_cost": "unit_price * (1 + duty_rate) + freight_per_unit",
        "weights": WEIGHT_NOTE,
        "moq": "raw need of 0 stays 0; a positive need is snapped to the order multiple and then to MOQ",
    },
    COMPETITOR_VERSION: {
        "price_drop": "price change percent <= -0.03",
        "bsr_jump": "older BSR - newer BSR >= 200 (rank number improved)",
        "rating_drop": "older rating - newer rating >= 0.2",
        "complaint_spike": "negative review hits increased by at least 10",
        "origin": "imported snapshots only; collection_method is demo_seed, manual_import, or licensed_feed",
    },
    PRICE_SIM_VERSION: {
        "scale": "target_price / current_list_price",
        "scaled_contribution": "net_sales * scale - net_cogs - platform_fees * scale - shipping_fees - other_fees",
        "unit_margin": "scaled_contribution / (net_sales * scale), null status zero_net_sales or negative_net_sales",
        "break_even_acos": "scaled_contribution / scaled net sales when both are positive; otherwise null with a status",
        "volume_multiplier": "max(0, 1 + elasticity * (target_price - current_price) / current_price)",
        "elasticities": "conservative -1.6, base -1.0, optimistic -0.4; optimistic means less elastic",
        "profit_delta": "base scenario period profit minus baseline period profit; ad spend does not scale",
        "zero_units": "no observed units yields status zero_units and does not invent rates",
    },
    SOP_VERSION: {
        "ranker": "BM25 with k1=1.5 and b=0.75",
        "tokenizer": "latin words plus CJK bigrams",
        "citation": "doc_id, section, and a quote that is an exact slice of the markdown file",
    },
}
