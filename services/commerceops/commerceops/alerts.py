"""Structured anomaly brief built only from engine output."""

from __future__ import annotations

from sqlalchemy.orm import Session

from commerceops.reporting import ads_report, competitor_report, inventory_report, profit_report
from commerceops.seed import AS_OF, CURRENT_END, CURRENT_START

_LAMP = "NS-LAMP-LED"


def anomaly_brief(session: Session, store_code: str) -> dict:
    profit = profit_report(session, store_code, CURRENT_START, CURRENT_END, compare=True)
    ads = ads_report(session, store_code, CURRENT_START, CURRENT_END, compare=True)
    inventory = inventory_report(session, store_code, AS_OF, horizon_days=14)
    alerts: list[dict] = []
    delta = profit["bridge"].delta_net_profit
    if delta < 0:
        drags = ", ".join(
            f"{item.code} {item.contribution}" for item in profit["drags"][:3]
        )
        alerts.append(
            {
                "code": "profit_drop",
                "detail": (
                    f"net profit {profit['previous'].net_profit} -> {profit['current'].net_profit} "
                    f"(delta {delta}). Drags: {drags}."
                ),
            }
        )
    for campaign in ads["campaigns"]:
        if campaign["budget"].reason == "no_adjustment":
            continue
        alerts.append(
            {
                "code": "ad_anomaly",
                "detail": (
                    f"{campaign['campaign_external_id']} {campaign['budget'].reason} "
                    f"{campaign['budget'].current_daily_budget} -> {campaign['budget'].suggested_daily_budget}"
                ),
            }
        )
    for sku in inventory["at_risk_skus"]:
        row = next(item for item in inventory["skus"] if item["sku"] == sku)
        alerts.append(
            {
                "code": "stockout_risk",
                "detail": f"{sku} days of cover {row['cover'].days_of_cover}",
            }
        )
    if store_code == "us-main":
        competitors = competitor_report(session, store_code, _LAMP, AS_OF)
        for comparison in competitors["comparisons"]:
            if not comparison.get("alerts"):
                continue
            alerts.append(
                {
                    "code": "competitor_alert",
                    "detail": (
                        f"{comparison['competitor_asin']} {', '.join(comparison['alerts'])} "
                        f"source {comparison.get('source', '')}"
                    ),
                }
            )
    return {
        "store_code": store_code,
        "period": {"start": CURRENT_START, "end": CURRENT_END},
        "as_of": AS_OF,
        "alerts": alerts,
    }
