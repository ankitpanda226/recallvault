"""Conflict resolution.

When a new verified fact arrives with the same key as an existing active
fact, we either:
  - do nothing (values are equivalent)
  - mark old as superseded, store new as version N+1 (newer_explicit_wins)
  - log for manual review (ask_user strategy — not default in MVP)

Every resolution creates a row in memory_conflicts and an event entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import MemoryConflict, MemoryFact
from app.services.event_logger import log_event
from app.utils.time import new_id, utcnow


@dataclass
class ResolutionOutcome:
    action: str  # "inserted" | "no_op" | "superseded" | "flagged"
    fact_id: str | None
    previous_fact_id: str | None
    version: int


def _equivalent(a: Any, b: Any) -> bool:
    if isinstance(a, list) and isinstance(b, list):
        return sorted(map(str, a)) == sorted(map(str, b))
    return str(a).strip().lower() == str(b).strip().lower()


def resolve_and_store(
    session: Session,
    project_id: str,
    key: str,
    value: Any,
    value_type: str,
    confidence: float,
    source_chunk_id: str | None,
    source_type: str,
) -> ResolutionOutcome:
    existing: MemoryFact | None = (
        session.query(MemoryFact)
        .filter(
            MemoryFact.project_id == project_id,
            MemoryFact.key == key,
            MemoryFact.status == "active",
        )
        .order_by(MemoryFact.version.desc())
        .first()
    )

    now = utcnow()

    # No prior fact — simple insert, version 1
    if existing is None:
        fact_id = new_id("f")
        fact = MemoryFact(
            fact_id=fact_id,
            project_id=project_id,
            key=key,
            value_json=value,
            value_type=value_type,
            confidence=confidence,
            source_chunk_id=source_chunk_id,
            source_type=source_type,
            version=1,
            status="active",
            created_at=now,
            updated_at=now,
        )
        session.add(fact)
        log_event(session, project_id, "FACT_CREATED", {
            "fact_id": fact_id, "key": key, "version": 1,
        })
        return ResolutionOutcome("inserted", fact_id, None, 1)

    # Equivalent value — update timestamp and strengthen confidence, no new version
    if _equivalent(existing.value_json, value):
        existing.updated_at = now
        existing.confidence = max(existing.confidence, confidence)
        log_event(session, project_id, "FACT_REAFFIRMED", {
            "fact_id": existing.fact_id, "key": key, "version": existing.version,
        })
        return ResolutionOutcome("no_op", existing.fact_id, existing.fact_id, existing.version)

    # Genuine conflict
    if settings.conflict_strategy == "ask_user":
        # Flag without mutating the active fact
        conflict = MemoryConflict(
            conflict_id=new_id("cf"),
            project_id=project_id,
            fact_key=key,
            old_fact_id=existing.fact_id,
            new_fact_id=None,
            resolution="pending_user_review",
            created_at=now,
        )
        session.add(conflict)
        log_event(session, project_id, "CONFLICT_FLAGGED", {
            "conflict_id": conflict.conflict_id, "key": key,
        })
        return ResolutionOutcome("flagged", existing.fact_id, existing.fact_id, existing.version)

    # Default: newer_explicit_wins
    existing.status = "superseded"
    existing.updated_at = now

    new_fact_id = new_id("f")
    new_fact = MemoryFact(
        fact_id=new_fact_id,
        project_id=project_id,
        key=key,
        value_json=value,
        value_type=value_type,
        confidence=confidence,
        source_chunk_id=source_chunk_id,
        source_type=source_type,
        version=existing.version + 1,
        status="active",
        created_at=now,
        updated_at=now,
    )
    session.add(new_fact)

    conflict = MemoryConflict(
        conflict_id=new_id("cf"),
        project_id=project_id,
        fact_key=key,
        old_fact_id=existing.fact_id,
        new_fact_id=new_fact_id,
        resolution="newer_explicit_wins",
        created_at=now,
    )
    session.add(conflict)

    log_event(session, project_id, "FACT_SUPERSEDED", {
        "old_fact_id": existing.fact_id,
        "new_fact_id": new_fact_id,
        "key": key,
        "old_version": existing.version,
        "new_version": new_fact.version,
    })

    return ResolutionOutcome("superseded", new_fact_id, existing.fact_id, new_fact.version)
