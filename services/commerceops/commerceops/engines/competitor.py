"""Competitor snapshot diff, formula competitor.v1.

Compares two imported snapshots for one competitor. A price drop alerts when
the percent change is <= -price_drop_pct. A BSR jump alerts when the rank
number improves (gets smaller) by at least bsr_jump_min. Rating and complaint
alerts use absolute drops and hit-count increases.

There is no fetcher here. Snapshots carry source, collection method, and
captured_at. Suggested actions are filled from those numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from commerceops.engines.money import money_str, ratio_str, require_int, require_non_negative

FORMULA_VERSION = "competitor.v1"

ALERT_ORDER = ("price_drop", "bsr_jump", "rating_drop", "complaint_spike")
ACTION_FOR_ALERT = {
    "price_drop": "review_price_and_coupon",
    "bsr_jump": "defend_share_of_voice",
    "rating_drop": "harvest_competitor_weakness",
    "complaint_spike": "mine_negative_review_keywords",
}


@dataclass(frozen=True)
class CompetitorPolicy:
    price_drop_pct: Decimal = Decimal("0.03")
    bsr_jump_min: int = 200
    rating_drop_min: Decimal = Decimal("0.2")
    complaint_increase_min: int = 10


@dataclass(frozen=True)
class Snapshot:
    competitor_asin: str
    competitor_title: str
    captured_at: str
    source: str
    collection_method: str
    price: Decimal
    currency: str
    bsr: int | None
    rating: Decimal | None
    review_count: int
    negative_review_hits: int
    negative_keywords: str


def _check(snapshot: Snapshot) -> None:
    if not snapshot.competitor_asin:
        raise ValueError("competitor_asin is required")
    if not snapshot.captured_at or not snapshot.source or not snapshot.collection_method:
        raise ValueError("captured_at, source, and collection_method are required")
    require_non_negative("price", snapshot.price)
    require_int("review_count", snapshot.review_count)
    require_int("negative_review_hits", snapshot.negative_review_hits)
    if snapshot.bsr is not None:
        require_int("bsr", snapshot.bsr, minimum=1)
    if snapshot.rating is not None:
        rating = require_non_negative("rating", snapshot.rating)
        if rating > 5:
            raise ValueError("rating must be <= 5")


def _action(alert: str, older: Snapshot, newer: Snapshot, evidence: dict) -> dict:
    return {
        "code": ACTION_FOR_ALERT[alert],
        "alert": alert,
        "competitor_asin": newer.competitor_asin,
        "detail": _detail(alert, older, newer, evidence),
        "evidence": evidence,
    }


def _detail(alert: str, older: Snapshot, newer: Snapshot, evidence: dict) -> str:
    origin = (
        f"Source {newer.source} captured {newer.captured_at}. "
        f"Collection method {newer.collection_method}."
    )
    if alert == "price_drop":
        return (
            f"Competitor {newer.competitor_asin} price moved from {money_str(older.price)} "
            f"to {money_str(newer.price)} ({evidence['price_change_pct']}). {origin}"
        )
    if alert == "bsr_jump":
        return (
            f"Competitor {newer.competitor_asin} BSR improved from {older.bsr} to {newer.bsr}. {origin}"
        )
    if alert == "rating_drop":
        return (
            f"Competitor {newer.competitor_asin} rating moved from {older.rating} to {newer.rating}. {origin}"
        )
    return (
        f"Competitor {newer.competitor_asin} negative review hits moved from "
        f"{older.negative_review_hits} to {newer.negative_review_hits}. "
        f"Keywords: {newer.negative_keywords or 'n/a'}. {origin}"
    )


def diff_snapshots(
    older: Snapshot,
    newer: Snapshot,
    policy: CompetitorPolicy | None = None,
) -> dict:
    rules = policy or CompetitorPolicy()
    _check(older)
    _check(newer)
    if older.competitor_asin != newer.competitor_asin:
        raise ValueError("snapshots must be the same competitor")
    if newer.captured_at <= older.captured_at:
        raise ValueError("snapshots must be in time order")
    price_change = newer.price - older.price
    if older.price == 0:
        price_change_pct = None
        price_status = "zero_base_price"
    else:
        price_change_pct = price_change / older.price
        price_status = "ok"
    bsr_change = None if older.bsr is None or newer.bsr is None else newer.bsr - older.bsr
    rating_change = None if older.rating is None or newer.rating is None else newer.rating - older.rating
    complaint_change = newer.negative_review_hits - older.negative_review_hits
    alerts: list[str] = []
    if price_change_pct is not None and price_change_pct <= -rules.price_drop_pct:
        alerts.append("price_drop")
    if older.bsr is not None and newer.bsr is not None and (older.bsr - newer.bsr) >= rules.bsr_jump_min:
        alerts.append("bsr_jump")
    if (
        older.rating is not None
        and newer.rating is not None
        and (older.rating - newer.rating) >= rules.rating_drop_min
    ):
        alerts.append("rating_drop")
    if complaint_change >= rules.complaint_increase_min:
        alerts.append("complaint_spike")
    evidence = {
        "price_change": money_str(price_change),
        "price_change_pct": ratio_str(price_change_pct),
        "price_status": price_status,
        "bsr_change": bsr_change,
        "rating_change": None if rating_change is None else format(rating_change, "f"),
        "complaint_change": complaint_change,
        "source": newer.source,
        "collection_method": newer.collection_method,
        "older_captured_at": older.captured_at,
        "newer_captured_at": newer.captured_at,
        "negative_keywords": newer.negative_keywords,
    }
    actions = [_action(alert, older, newer, evidence) for alert in alerts]
    return {
        "formula_version": FORMULA_VERSION,
        "status": "ok",
        "competitor_asin": newer.competitor_asin,
        "competitor_title": newer.competitor_title,
        "older_price": older.price,
        "newer_price": newer.price,
        "older_captured_at": older.captured_at,
        "newer_captured_at": newer.captured_at,
        "source": newer.source,
        "collection_method": newer.collection_method,
        "price_change": price_change,
        "price_change_pct": price_change_pct,
        "price_status": price_status,
        "bsr_change": bsr_change,
        "rating_change": rating_change,
        "complaint_change": complaint_change,
        "alerts": alerts,
        "suggested_actions": actions,
    }


def diff_history(snapshots: list[Snapshot] | tuple[Snapshot, ...], policy: CompetitorPolicy | None = None) -> dict:
    ordered = sorted(snapshots, key=lambda item: item.captured_at)
    if len(ordered) < 2:
        asin = ordered[0].competitor_asin if ordered else ""
        return {
            "formula_version": FORMULA_VERSION,
            "status": "insufficient_history",
            "competitor_asin": asin,
            "newer_price": ordered[0].price if ordered else None,
            "newer_captured_at": ordered[0].captured_at if ordered else None,
            "alerts": [],
            "suggested_actions": [],
            "source": ordered[0].source if ordered else "",
            "collection_method": ordered[0].collection_method if ordered else "",
        }
    return diff_snapshots(ordered[-2], ordered[-1], policy)
