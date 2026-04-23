"""SQLAlchemy models.

Two logical databases:
  1. registry.db — global, tracks projects
  2. data/{project_id}/facts.db — per-project: chunks metadata, facts,
     conflicts, events

Both use the same Base class but are bound to different engines at runtime.
"""
from __future__ import annotations

from datetime import datetime
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    JSON,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


# ---- Registry (global) ----

class Project(Base):
    __tablename__ = "projects"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    description = Column(Text, default="")
    config_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


# ---- Per-project tables ----

class MemoryChunk(Base):
    __tablename__ = "memory_chunks"

    chunk_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    speaker = Column(String, nullable=False)  # 'user' | 'assistant' | 'system'
    raw_text = Column(Text, nullable=False)
    tags_json = Column(JSON, default=list)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)


class MemoryFact(Base):
    __tablename__ = "memory_facts"

    fact_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    key = Column(String, nullable=False, index=True)
    value_json = Column(JSON, nullable=False)
    value_type = Column(String, default="string")
    confidence = Column(Float, default=1.0)
    source_chunk_id = Column(String, ForeignKey("memory_chunks.chunk_id"), nullable=True)
    source_type = Column(String, default="explicit_user_statement")
    version = Column(Integer, default=1, nullable=False)
    status = Column(String, default="active", nullable=False, index=True)  # active | superseded | deleted
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)


Index("ix_facts_project_key_status", MemoryFact.project_id, MemoryFact.key, MemoryFact.status)


class MemoryConflict(Base):
    __tablename__ = "memory_conflicts"

    conflict_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    fact_key = Column(String, nullable=False)
    old_fact_id = Column(String, nullable=True)
    new_fact_id = Column(String, nullable=True)
    resolution = Column(String, default="newer_explicit_wins")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class MemoryEvent(Base):
    __tablename__ = "memory_events"

    event_id = Column(String, primary_key=True)
    project_id = Column(String, nullable=False, index=True)
    event_type = Column(String, nullable=False, index=True)
    payload_json = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
