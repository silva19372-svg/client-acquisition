from __future__ import annotations

import os
from dataclasses import dataclass


def _positive_int(name: str, default: int, maximum: int) -> int:
    raw = str(os.getenv(name, default)).strip()
    try:
        value = int(raw)
    except ValueError:
        value = default
    return max(1, min(maximum, value))


@dataclass(frozen=True)
class Settings:
    database_url: str
    portal_shared_secret: str
    city: str
    batch_size: int
    ready_reserve: int
    daily_limit: int

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=str(os.getenv("DATABASE_URL") or "").strip(),
            portal_shared_secret=str(os.getenv("PORTAL_SHARED_SECRET") or "").strip(),
            city=str(os.getenv("CITY") or "Bangalore").strip() or "Bangalore",
            batch_size=_positive_int("BATCH_SIZE", 10, 20),
            ready_reserve=_positive_int("READY_RESERVE", 10, 500),
            daily_limit=_positive_int("DAILY_LIMIT", 20, 100),
        )
