from decimal import Decimal

import pytest

from commerceops.engines.competitor import CompetitorPolicy, Snapshot, diff_history, diff_snapshots


def _snap(**overrides) -> Snapshot:
    base = dict(
        competitor_asin="B0TEST",
        competitor_title="Test Lamp",
        captured_at="2026-03-01T00:00:00Z",
        source="demo_seed",
        collection_method="demo_seed",
        price=Decimal("100"),
        currency="USD",
        bsr=1000,
        rating=Decimal("4.5"),
        review_count=10,
        negative_review_hits=1,
        negative_keywords="cord",
    )
    base.update(overrides)
    return Snapshot(**base)


def test_threshold_boundaries():
    drop = diff_snapshots(_snap(), _snap(captured_at="2026-03-14T00:00:00Z", price=Decimal("97")))
    assert drop["alerts"] == ["price_drop"]
    assert drop["price_change_pct"] == Decimal("-0.03")
    no_drop = diff_snapshots(_snap(), _snap(captured_at="2026-03-14T00:00:00Z", price=Decimal("98")))
    assert "price_drop" not in no_drop["alerts"]
    jump = diff_snapshots(_snap(), _snap(captured_at="2026-03-14T00:00:00Z", bsr=800))
    assert jump["alerts"] == ["bsr_jump"]
    assert "bsr_jump" not in diff_snapshots(_snap(), _snap(captured_at="2026-03-14T00:00:00Z", bsr=801))["alerts"]
    worse = diff_snapshots(_snap(), _snap(captured_at="2026-03-14T00:00:00Z", bsr=1300))
    assert "bsr_jump" not in worse["alerts"]
    rating = diff_snapshots(_snap(), _snap(captured_at="2026-03-14T00:00:00Z", rating=Decimal("4.3")))
    assert rating["alerts"] == ["rating_drop"]
    complaints = diff_snapshots(_snap(), _snap(captured_at="2026-03-14T00:00:00Z", negative_review_hits=11))
    assert complaints["alerts"] == ["complaint_spike"]
    assert "complaint_spike" not in diff_snapshots(
        _snap(), _snap(captured_at="2026-03-14T00:00:00Z", negative_review_hits=10)
    )["alerts"]


def test_zero_base_price_and_missing_history():
    diff = diff_snapshots(_snap(price=Decimal("0")), _snap(captured_at="2026-03-14T00:00:00Z", price=Decimal("5")))
    assert diff["price_status"] == "zero_base_price"
    assert "price_drop" not in diff["alerts"]
    history = diff_history([_snap()])
    assert history["status"] == "insufficient_history"
    assert history["alerts"] == []


def test_actions_quote_source_and_numbers():
    diff = diff_snapshots(
        _snap(price=Decimal("42"), bsr=1200, negative_review_hits=4, negative_keywords="cord length"),
        _snap(
            captured_at="2026-03-14T00:00:00Z",
            price=Decimal("36"),
            bsr=400,
            negative_review_hits=18,
            negative_keywords="flicker, dead on arrival",
            source="demo_seed",
        ),
        CompetitorPolicy(),
    )
    codes = [action["code"] for action in diff["suggested_actions"]]
    assert codes == ["review_price_and_coupon", "defend_share_of_voice", "mine_negative_review_keywords"]
    text = " ".join(action["detail"] for action in diff["suggested_actions"])
    assert "42.0000" in text and "36.0000" in text
    assert "demo_seed" in text
    assert "B0TEST" in text
    assert diff["collection_method"] == "demo_seed"


def test_invalid_snapshots_fail():
    with pytest.raises(ValueError):
        diff_snapshots(_snap(rating=Decimal("6")), _snap(captured_at="2026-03-14T00:00:00Z"))
    with pytest.raises(ValueError):
        diff_snapshots(_snap(bsr=0), _snap(captured_at="2026-03-14T00:00:00Z"))
    with pytest.raises(ValueError):
        diff_snapshots(_snap(captured_at="2026-03-14T00:00:00Z"), _snap())
