"""Memory event logging.

Every mutation — chunk ingested, fact created/updated/deleted, conflict
detected — goes through here. The log is the audit trail the response guard
and admin dashboards read from.
"""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.db.models import MemoryEvent
from app.utils.time import new_id, utcnow


def log_event(
    session: Session,
    project_id: str,
    event_type: str,
    payload: dict[str, Any] | None = None,
) -> MemoryEvent:
    ev = MemoryEvent(
        event_id=new_id("ev"),
        project_id=project_id,
        event_type=event_type,
        payload_json=payload or {},
        created_at=utcnow(),
    )
    session.add(ev)
    return ev
