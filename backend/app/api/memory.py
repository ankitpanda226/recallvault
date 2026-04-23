"""Memory endpoints: search, facts, history, update, forget."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.db.models import MemoryFact
from app.db.session import project_session
from app.schemas.all import (
    FactForgetIn,
    FactOut,
    FactUpdateIn,
    IngestReportOut,
    FactActionOut,
    MemoryIngestIn,
    SearchHit,
    SearchOut,
)
from app.services import ingest_service, retrieval_service
from app.services.conflict_resolver import resolve_and_store
from app.services.event_logger import log_event
from app.utils.time import utcnow

router = APIRouter(prefix="/memory", tags=["memory"])


@router.post("/ingest", response_model=IngestReportOut)
def ingest_memory(body: MemoryIngestIn) -> IngestReportOut:
    report = ingest_service.ingest(
        project_id=body.project_id,
        text=body.text,
        speaker=body.speaker,
        tags=body.tags,
    )
    return IngestReportOut(
        project_id=report.project_id,
        chunk_ids=report.chunk_ids,
        candidates=report.candidates,
        accepted=report.accepted,
        rejected=report.rejected,
        facts=[
            FactActionOut(
                key=f.key, value=f.value, action=f.action,
                reason=f.reason, fact_id=f.fact_id, version=f.version,
            )
            for f in report.facts
        ],
    )


@router.get("/search", response_model=SearchOut)
def search(
    project_id: str = Query(...),
    q: str = Query(..., min_length=1),
) -> SearchOut:
    result = retrieval_service.retrieve(project_id, q)
    hits: list[SearchHit] = []
    for f in result.fact_hits:
        hits.append(SearchHit(
            kind="fact",
            score=f.score,
            payload={
                "fact_id": f.fact_id,
                "key": f.key,
                "value": f.value,
                "confidence": f.confidence,
                "version": f.version,
                "source_chunk_id": f.source_chunk_id,
                "source_type": f.source_type,
                "match_reason": f.match_reason,
            },
        ))
    for c in result.chunk_hits:
        hits.append(SearchHit(
            kind="chunk",
            score=c.score,
            payload={
                "chunk_id": c.chunk_id,
                "text": c.text,
                "speaker": c.speaker,
                "similarity": c.similarity,
                "created_at": c.created_at.isoformat() if c.created_at else None,
            },
        ))
    return SearchOut(query=q, project_id=project_id, results=hits)


@router.get("/facts/{key}", response_model=FactOut)
def get_fact(key: str, project_id: str = Query(...)) -> FactOut:
    with project_session(project_id) as s:
        row = (
            s.query(MemoryFact)
            .filter(
                MemoryFact.project_id == project_id,
                MemoryFact.key == key,
                MemoryFact.status == "active",
            )
            .order_by(MemoryFact.version.desc())
            .first()
        )
        if row is None:
            raise HTTPException(404, f"no active fact for key '{key}'")
        return FactOut(
            fact_id=row.fact_id, key=row.key, value=row.value_json,
            value_type=row.value_type, confidence=row.confidence,
            version=row.version, status=row.status,
            source_chunk_id=row.source_chunk_id, source_type=row.source_type,
            created_at=row.created_at, updated_at=row.updated_at,
        )


@router.get("/history/{key}", response_model=list[FactOut])
def get_history(key: str, project_id: str = Query(...)) -> list[FactOut]:
    with project_session(project_id) as s:
        rows = (
            s.query(MemoryFact)
            .filter(MemoryFact.project_id == project_id, MemoryFact.key == key)
            .order_by(MemoryFact.version.asc())
            .all()
        )
        return [
            FactOut(
                fact_id=r.fact_id, key=r.key, value=r.value_json,
                value_type=r.value_type, confidence=r.confidence,
                version=r.version, status=r.status,
                source_chunk_id=r.source_chunk_id, source_type=r.source_type,
                created_at=r.created_at, updated_at=r.updated_at,
            )
            for r in rows
        ]


@router.post("/update", response_model=FactOut)
def update_fact(body: FactUpdateIn) -> FactOut:
    """Explicit update — routes through the conflict resolver so the version
    chain is maintained exactly as if the fact came from ingestion."""
    with project_session(body.project_id) as s:
        outcome = resolve_and_store(
            session=s,
            project_id=body.project_id,
            key=body.key,
            value=body.value,
            value_type=body.value_type,
            confidence=body.confidence,
            source_chunk_id=None,
            source_type=body.source_type,
        )
        s.flush()
        row = (
            s.query(MemoryFact)
            .filter(MemoryFact.fact_id == outcome.fact_id)
            .first()
        )
        if row is None:
            raise HTTPException(500, "fact not persisted")
        return FactOut(
            fact_id=row.fact_id, key=row.key, value=row.value_json,
            value_type=row.value_type, confidence=row.confidence,
            version=row.version, status=row.status,
            source_chunk_id=row.source_chunk_id, source_type=row.source_type,
            created_at=row.created_at, updated_at=row.updated_at,
        )


@router.post("/forget")
def forget_fact(body: FactForgetIn) -> dict:
    with project_session(body.project_id) as s:
        row = (
            s.query(MemoryFact)
            .filter(
                MemoryFact.project_id == body.project_id,
                MemoryFact.key == body.key,
                MemoryFact.status == "active",
            )
            .order_by(MemoryFact.version.desc())
            .first()
        )
        if row is None:
            raise HTTPException(404, f"no active fact for key '{body.key}'")
        row.status = "deleted"
        row.updated_at = utcnow()
        log_event(s, body.project_id, "FACT_DELETED", {
            "fact_id": row.fact_id, "key": body.key, "version": row.version,
        })
        return {"forgotten": row.fact_id, "key": body.key, "version": row.version}
