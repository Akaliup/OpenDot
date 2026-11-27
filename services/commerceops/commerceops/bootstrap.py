"""First-boot demo seed. A database that already has stores is left alone."""

from __future__ import annotations

from sqlalchemy import func, select

from commerceops.db import session_scope
from commerceops.models import Store
from commerceops.seed import seed_demo_data


def seed_if_empty(database_url: str | None = None) -> bool:
    with session_scope(database_url) as session:
        count = session.scalar(select(func.count()).select_from(Store)) or 0
        if count:
            return False
        seed_demo_data(session)
        return True
