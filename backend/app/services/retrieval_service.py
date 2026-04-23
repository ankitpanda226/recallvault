"""Retrieval pipeline.

Hybrid retrieval per architecture section 12:

  1. Structured lookup     — exact fact key + alias match (active facts only)
  2. Semantic retrieval    — top-K from ChromaDB
  3. Rerank                — combine signals
  4. (Guard decides answer — see response_guard.py)

This module is pure retrieval — the guard decides how to answer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.models import MemoryChunk, MemoryFact
from app.db.session import project_session
from app.services import embedding_service
from app.utils.time import recency_score, utcnow


# Natural-language cues that hint at a particular fact key. Keeps the MVP
# query-classification work deterministic and debuggable.
_KEY_ALIASES: dict[str, list[re.Pattern[str]]] = {
    "user_name": [re.compile(r"\bmy name\b", re.I), re.compile(r"\bwho am i\b", re.I)],
    "graduation_date": [
        re.compile(r"\bgraduat\w*", re.I),
        re.compile(r"\bfinish school\b", re.I),
        re.compile(r"\bwhen do i (?:finish|graduate)\b", re.I),
    ],
    "preferred_roles": [
        re.compile(r"\b(?:preferred|target) roles?\b", re.I),
        re.compile(r"\bwhat kind of (?:roles?|jobs?)\b", re.I),
        re.compile(r"\btargeting\b", re.I),
    ],
    "response_style_preference": [
        re.compile(r"\b(?:response|answer) style\b", re.I),
        re.compile(r"\bhow (?:do i want|should i)\b", re.I),
    ],
    "architecture_decision": [
        re.compile(r"\barchitecture decision\b", re.I),
        re.compile(r"\bwhat did we (?:choose|decide|pick)\b", re.I),
        re.compile(r"\bmemory storage\b", re.I),
        re.compile(r"\bwhat (?:db|database)\b", re.I),
    ],
    "bug_root_cause": [
        re.compile(r"\broot cause\b", re.I),
        re.compile(r"\bwhy did .* break\b", re.I),
    ],
    "company_targets": [
        re.compile(r"\b(?:target|targeted) companies?\b", re.I),
        re.compile(r"\bwhich companies\b", re.I),
    ],
}


@dataclass
class FactHit:
    fact_id: str
    key: str
    value: Any
    value_type: str
    confidence: float
    version: int
    source_chunk_id: str | None
    source_type: str
    created_at: Any
    updated_at: Any
    match_reason: str
    score: float = 0.0


@dataclass
class ChunkHit:
    chunk_id: str
    text: str
    speaker: str
    created_at: Any
    similarity: float
    score: float = 0.0


@dataclass
class RetrievalResult:
    query: str
    project_id: str
    fact_hits: list[FactHit] = field(default_factory=list)
    chunk_hits: list[ChunkHit] = field(default_factory=list)
    matched_keys: list[str] = field(default_factory=list)


def _keys_from_query(query: str) -> list[str]:
    out: list[str] = []
    for key, patterns in _KEY_ALIASES.items():
        if any(p.search(query) for p in patterns):
            out.append(key)
    return out


def _lookup_facts(
    session: Session, project_id: str, keys: list[str]
) -> list[FactHit]:
    if not keys:
        return []
    rows = (
        session.query(MemoryFact)
        .filter(
            MemoryFact.project_id == project_id,
            MemoryFact.status == "active",
            MemoryFact.key.in_(keys),
        )
        .all()
    )
    hits: list[FactHit] = []
    for r in rows:
        hits.append(
            FactHit(
                fact_id=r.fact_id,
                key=r.key,
                value=r.value_json,
                value_type=r.value_type,
                confidence=r.confidence,
                version=r.version,
                source_chunk_id=r.source_chunk_id,
                source_type=r.source_type,
                created_at=r.created_at,
                updated_at=r.updated_at,
                match_reason=f"exact key match on '{r.key}'",
            )
        )
    return hits


def _source_quality(source_type: str) -> float:
    return {
        "explicit_user_statement": 1.0,
        "decision": 0.9,
        "inferred": 0.6,
    }.get(source_type, 0.5)


def _rerank_facts(facts: list[FactHit]) -> list[FactHit]:
    now = utcnow()
    for f in facts:
        r = recency_score(f.updated_at, now, settings.recency_half_life_days)
        # Weighted blend — confidence and source quality dominate, recency
        # breaks ties. Keeps the signal easy to explain in an interview.
        f.score = 0.5 * f.confidence + 0.3 * _source_quality(f.source_type) + 0.2 * r
    facts.sort(key=lambda f: f.score, reverse=True)
    return facts


def _rerank_chunks(chunks: list[ChunkHit]) -> list[ChunkHit]:
    now = utcnow()
    for c in chunks:
        r = recency_score(c.created_at, now, settings.recency_half_life_days)
        c.score = 0.75 * c.similarity + 0.25 * r
    chunks.sort(key=lambda c: c.score, reverse=True)
    return chunks


def retrieve(project_id: str, query: str, top_k: int | None = None) -> RetrievalResult:
    top_k = top_k or settings.top_k_semantic
    result = RetrievalResult(query=query, project_id=project_id)

    # Stage 1: infer likely fact keys from the query
    keys = _keys_from_query(query)
    result.matched_keys = keys

    # Stage 2: structured fact lookup
    with project_session(project_id) as session:
        if keys:
            result.fact_hits = _rerank_facts(_lookup_facts(session, project_id, keys))

        # Stage 3: semantic retrieval + attach chunk metadata from SQL for speaker/created_at
        sem = embedding_service.search(project_id, query, top_k=top_k)
        if sem:
            chunk_ids = [s["chunk_id"] for s in sem]
            rows = {
                r.chunk_id: r
                for r in session.query(MemoryChunk)
                .filter(
                    MemoryChunk.project_id == project_id,
                    MemoryChunk.chunk_id.in_(chunk_ids),
                )
                .all()
            }
            chunks: list[ChunkHit] = []
            for s in sem:
                row = rows.get(s["chunk_id"])
                if row is None:
                    continue
                chunks.append(
                    ChunkHit(
                        chunk_id=row.chunk_id,
                        text=row.raw_text,
                        speaker=row.speaker,
                        created_at=row.created_at,
                        similarity=s["similarity"],
                    )
                )
            result.chunk_hits = _rerank_chunks(chunks)

    return result
