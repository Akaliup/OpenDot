"""Seed the configured workspace on first boot when it has no stores."""

from __future__ import annotations

import os

from sqlalchemy import func, select

from commerceops.context import DEMO_WORKSPACE
from commerceops.db import session_scope
from commerceops.models import Store
from commerceops.seed import seed_demo_data


def seed_if_empty(database_url: str | None = None, workspace: str | None = None) -> bool:
    workspace = workspace or os.environ.get("COMMERCEOPS_WORKSPACE_ID", DEMO_WORKSPACE)
    with session_scope(database_url) as session:
        count = session.scalar(select(func.count()).select_from(Store).where(Store.workspace_id == workspace)) or 0
        if count:
            return False
        seed_demo_data(session, workspace)
        return True
