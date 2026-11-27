"""Inclusive date windows. The previous window has the same length."""

from __future__ import annotations

from datetime import date, timedelta


def previous_period(start: date, end: date) -> tuple[date, date]:
    if end < start:
        raise ValueError("end before start")
    span = (end - start).days + 1
    if span > 366:
        raise ValueError("window exceeds 366 days")
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return prev_start, prev_end
