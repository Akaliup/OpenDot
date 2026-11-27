"""Process settings. The default database is a local SQLite file."""

from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_DATABASE_URL = "sqlite:///./commerceops.db"


@dataclass(frozen=True)
class Settings:
    database_url: str


def get_settings() -> Settings:
    return Settings(os.environ.get("COMMERCEOPS_DATABASE_URL", DEFAULT_DATABASE_URL))
