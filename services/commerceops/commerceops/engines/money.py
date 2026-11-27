"""Decimal constructors shared by the engines. Floats are rejected."""

from __future__ import annotations

from decimal import Decimal, ROUND_HALF_EVEN


def D(value: Decimal | int | str) -> Decimal:
    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError("money and ratios reject bool and float; pass Decimal or str")
    if isinstance(value, Decimal):
        decimal = value
    elif isinstance(value, int):
        decimal = Decimal(value)
    elif isinstance(value, str):
        decimal = Decimal(value.strip())
    else:
        raise TypeError(f"unsupported decimal source: {type(value).__name__}")
    if not decimal.is_finite():
        raise ValueError("non-finite decimal")
    return decimal


def q_money(value: Decimal) -> Decimal:
    return value.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN)


def money_str(value: Decimal) -> str:
    return format(q_money(value), "f")


def ratio_str(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_EVEN), "f")


def require_non_negative(name: str, value: Decimal) -> Decimal:
    if value < 0:
        raise ValueError(f"{name} must be >= 0")
    return value


def require_int(name: str, value: int, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{name} must be an int")
    if value < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return value
