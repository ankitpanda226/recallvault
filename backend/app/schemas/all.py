"""Pydantic schemas for the API."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---- Projects ----

class ProjectCreateIn(BaseModel):
    id: str = Field(..., pattern=r"^[a-z0-9_\-]{2,64}$")
    name: str
    description: str = ""


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    created_at: datetime


# ---- Chat ----

class ChatMessageIn(BaseModel):
    project_id: str
    text: str
    speaker: str = "user"
    tags: list[str] | None = None


class FactActionOut(BaseModel):
    key: str
    value: Any
    action: str
    reason: str | None = None
    fact_id: str | None = None
    version: int | None = None


class IngestReportOut(BaseModel):
    project_id: str
    chunk_ids: list[str]
    candidates: int
    accepted: int
    rejected: int
    facts: list[FactActionOut]


class ChatRespondIn(BaseModel):
    project_id: str
    query: str


class ProvenanceOut(BaseModel):
    source_chunk_id: str | None
    source_type: str | None
    fact_id: str | None
    version: int | None
    created_at: str | None


class GuardedAnswerOut(BaseModel):
    mode: str
    answer: str
    provenance: list[ProvenanceOut]
    supporting_chunks: list[str]
    matched_keys: list[str]


# ---- Memory ----

class MemoryIngestIn(BaseModel):
    project_id: str
    text: str
    speaker: str = "user"
    tags: list[str] | None = None


class FactOut(BaseModel):
    fact_id: str
    key: str
    value: Any
    value_type: str
    confidence: float
    version: int
    status: str
    source_chunk_id: str | None
    source_type: str
    created_at: datetime
    updated_at: datetime


class SearchHit(BaseModel):
    kind: str  # "fact" | "chunk"
    score: float
    payload: dict[str, Any]


class SearchOut(BaseModel):
    query: str
    project_id: str
    results: list[SearchHit]


class FactUpdateIn(BaseModel):
    project_id: str
    key: str
    value: Any
    value_type: str = "string"
    confidence: float = 1.0
    source_type: str = "explicit_user_statement"


class FactForgetIn(BaseModel):
    project_id: str
    key: str


# ---- Admin ----

class StatsOut(BaseModel):
    project_id: str
    chunks: int
    active_facts: int
    superseded_facts: int
    conflicts: int
    events: int


class EventOut(BaseModel):
    event_id: str
    event_type: str
    payload: dict[str, Any]
    created_at: datetime


class ConflictOut(BaseModel):
    conflict_id: str
    fact_key: str
    old_fact_id: str | None
    new_fact_id: str | None
    resolution: str
    created_at: datetime
