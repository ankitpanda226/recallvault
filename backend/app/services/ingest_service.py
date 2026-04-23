"""Ingestion pipeline.

Orchestrates the full flow from incoming message to persisted memory:

  normalize -> chunk -> store raw -> embed -> extract candidates
  -> verify each -> resolve conflicts -> log events

Returns a structured report so callers (chat endpoint, tests) can see
exactly what happened.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.core.logging import get_logger
from app.db.models import MemoryChunk
from app.db.session import project_session
from app.services import embedding_service
from app.services.conflict_resolver import resolve_and_store
from app.services.event_logger import log_event
from app.services.fact_extractor import extract
from app.services.verifier import verify
from app.utils.chunking import chunk as chunk_text
from app.utils.chunking import normalize
from app.utils.time import new_id, utcnow

log = get_logger(__name__)


@dataclass
class FactReport:
    key: str
    value: Any
    action: str  # inserted | no_op | superseded | flagged | rejected
    reason: str = ""
    fact_id: str | None = None
    version: int | None = None


@dataclass
class IngestReport:
    project_id: str
    chunk_ids: list[str] = field(default_factory=list)
    candidates: int = 0
    accepted: int = 0
    rejected: int = 0
    facts: list[FactReport] = field(default_factory=list)


def ingest(
    project_id: str,
    text: str,
    speaker: str = "user",
    tags: list[str] | None = None,
) -> IngestReport:
    text = normalize(text)
    report = IngestReport(project_id=project_id)
    if not text:
        return report

    pieces = chunk_text(text)
    now = utcnow()

    with project_session(project_id) as session:
        for piece in pieces:
            chunk_id = new_id("c")
            row = MemoryChunk(
                chunk_id=chunk_id,
                project_id=project_id,
                speaker=speaker,
                raw_text=piece,
                tags_json=tags or [],
                created_at=now,
            )
            session.add(row)
            log_event(session, project_id, "CHUNK_INGESTED", {
                "chunk_id": chunk_id,
                "speaker": speaker,
                "length": len(piece),
            })
            report.chunk_ids.append(chunk_id)

            # Embed + persist to vector store (outside SQL transaction is fine;
            # Chroma has its own persistence).
            try:
                embedding_service.add_chunk(
                    project_id=project_id,
                    chunk_id=chunk_id,
                    text=piece,
                    metadata={
                        "speaker": speaker,
                        "created_at": now.isoformat(),
                    },
                )
            except Exception as e:  # embedding failure should not block raw storage
                log.warning("embedding failed for chunk %s: %s", chunk_id, e)

            # Fact extraction — only on user speech in MVP
            if speaker != "user":
                continue

            candidates = extract(piece)
            report.candidates += len(candidates)

            for cand in candidates:
                result = verify(cand)
                if not result.accepted:
                    report.rejected += 1
                    report.facts.append(FactReport(
                        key=cand.key, value=cand.value,
                        action="rejected", reason=result.reason,
                    ))
                    log_event(session, project_id, "FACT_REJECTED", {
                        "key": cand.key, "reason": result.reason,
                    })
                    continue

                outcome = resolve_and_store(
                    session=session,
                    project_id=project_id,
                    key=cand.key,
                    value=cand.value,
                    value_type=cand.value_type,
                    confidence=cand.confidence,
                    source_chunk_id=chunk_id,
                    source_type=cand.source_type,
                )
                report.accepted += 1
                report.facts.append(FactReport(
                    key=cand.key,
                    value=cand.value,
                    action=outcome.action,
                    reason=cand.reason,
                    fact_id=outcome.fact_id,
                    version=outcome.version,
                ))

    return report
