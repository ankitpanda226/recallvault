"""Admin / observability endpoints."""
from __future__ import annotations

from fastapi import APIRouter, Query

from app.db.models import MemoryChunk, MemoryConflict, MemoryEvent, MemoryFact
from app.db.session import project_session
from app.schemas.all import ConflictOut, EventOut, StatsOut

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/stats", response_model=StatsOut)
def stats(project_id: str = Query(...)) -> StatsOut:
    with project_session(project_id) as s:
        chunks = s.query(MemoryChunk).filter(MemoryChunk.project_id == project_id).count()
        active = (
            s.query(MemoryFact)
            .filter(
                MemoryFact.project_id == project_id, MemoryFact.status == "active"
            )
            .count()
        )
        superseded = (
            s.query(MemoryFact)
            .filter(
                MemoryFact.project_id == project_id, MemoryFact.status == "superseded"
            )
            .count()
        )
        conflicts = (
            s.query(MemoryConflict)
            .filter(MemoryConflict.project_id == project_id)
            .count()
        )
        events = (
            s.query(MemoryEvent)
            .filter(MemoryEvent.project_id == project_id)
            .count()
        )
        return StatsOut(
            project_id=project_id,
            chunks=chunks, active_facts=active, superseded_facts=superseded,
            conflicts=conflicts, events=events,
        )


@router.get("/conflicts", response_model=list[ConflictOut])
def conflicts(project_id: str = Query(...)) -> list[ConflictOut]:
    with project_session(project_id) as s:
        rows = (
            s.query(MemoryConflict)
            .filter(MemoryConflict.project_id == project_id)
            .order_by(MemoryConflict.created_at.desc())
            .all()
        )
        return [
            ConflictOut(
                conflict_id=r.conflict_id, fact_key=r.fact_key,
                old_fact_id=r.old_fact_id, new_fact_id=r.new_fact_id,
                resolution=r.resolution, created_at=r.created_at,
            )
            for r in rows
        ]


@router.get("/events", response_model=list[EventOut])
def events(
    project_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
) -> list[EventOut]:
    with project_session(project_id) as s:
        rows = (
            s.query(MemoryEvent)
            .filter(MemoryEvent.project_id == project_id)
            .order_by(MemoryEvent.created_at.desc())
            .limit(limit)
            .all()
        )
        return [
            EventOut(
                event_id=r.event_id, event_type=r.event_type,
                payload=r.payload_json or {}, created_at=r.created_at,
            )
            for r in rows
        ]
