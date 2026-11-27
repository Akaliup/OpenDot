"""Exact decimal column type.

SQLite stores a canonical decimal string. Other dialects bind Decimal to
NUMERIC(18, 6). Reporting never uses SQL SUM for money.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Numeric, String
from sqlalchemy.types import TypeDecorator


class ExactNumeric(TypeDecorator):
    impl = String(40)
    cache_ok = True

    def load_dialect_impl(self, dialect):  # type: ignore[no-untyped-def]
        if dialect.name == "sqlite":
            return dialect.type_descriptor(String(40))
        return dialect.type_descriptor(Numeric(18, 6))

    def process_bind_param(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        if isinstance(value, bool) or isinstance(value, float):
            raise TypeError("ExactNumeric rejects bool and float")
        decimal = value if isinstance(value, Decimal) else Decimal(str(value))
        if not decimal.is_finite():
            raise ValueError("non-finite decimal")
        if dialect.name == "sqlite":
            return format(decimal, "f")
        return decimal

    def process_result_value(self, value, dialect):  # type: ignore[no-untyped-def]
        if value is None:
            return None
        return Decimal(str(value))
