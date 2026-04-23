"""Time and ID helpers."""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def new_id(prefix: str = "") -> str:
    raw = uuid.uuid4().hex[:12]
    return f"{prefix}_{raw}" if prefix else raw


def recency_score(created_at: datetime, now: datetime, half_life_days: float) -> float:
    """Exponential recency decay in [0, 1]; 1 means 'just now'."""
    delta = (now - created_at).total_seconds() / 86400.0
    if delta <= 0:
        return 1.0
    return math.exp(-math.log(2) * delta / half_life_days)
