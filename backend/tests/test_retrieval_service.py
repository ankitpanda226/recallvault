"""Unit tests for retrieval_service.retrieve().

embedding_service.search is patched per-test so no real ChromaDB or model
is needed. Structured fact lookup and chunk metadata joins use real SQLite.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from app.db.models import MemoryChunk, MemoryFact
from app.db.session import project_session
from app.utils.time import new_id, utcnow


# ── Helpers ───────────────────────────────────────────────────────────────────

def _add_chunk(project_id, chunk_id=None, text="hello world", speaker="user", created_at=None):
    chunk_id = chunk_id or new_id("c")
    with project_session(project_id) as s:
        s.add(MemoryChunk(
            chunk_id=chunk_id,
            project_id=project_id,
            speaker=speaker,
            raw_text=text,
            tags_json=[],
            created_at=created_at or utcnow(),
        ))
    return chunk_id


def _add_fact(project_id, key="user_name", value="Alice", confidence=0.9):
    now = utcnow()
    with project_session(project_id) as s:
        s.add(MemoryFact(
            fact_id=new_id("f"),
            project_id=project_id,
            key=key,
            value_json=value,
            value_type="string",
            confidence=confidence,
            source_chunk_id=None,
            source_type="explicit_user_statement",
            version=1,
            status="active",
            created_at=now,
            updated_at=now,
        ))


def _retrieve(project_id, query, mock_search_return=None, top_k=5):
    import app.services.retrieval_service as svc
    mock_emb = MagicMock()
    mock_emb.search.return_value = mock_search_return or []
    original = svc.embedding_service
    svc.embedding_service = mock_emb
    try:
        from app.services.retrieval_service import retrieve
        return retrieve(project_id, query, top_k=top_k)
    finally:
        svc.embedding_service = original


# ── Empty project ─────────────────────────────────────────────────────────────

def test_empty_project_returns_empty_result(test_project):
    result = _retrieve(test_project, "What is my name?")
    assert result.fact_hits == []
    assert result.chunk_hits == []


def test_result_carries_query_and_project_id(test_project):
    result = _retrieve(test_project, "hello query")
    assert result.query == "hello query"
    assert result.project_id == test_project


# ── Semantic chunk retrieval ───────────────────────────────────────────────────

def test_semantic_chunks_returned_from_mock(test_project):
    cid = _add_chunk(test_project, text="backend roles are great")
    sem = [{"chunk_id": cid, "similarity": 0.85}]
    result = _retrieve(test_project, "backend", mock_search_return=sem)
    assert len(result.chunk_hits) == 1
    assert result.chunk_hits[0].chunk_id == cid


def test_chunk_hit_similarity_preserved(test_project):
    cid = _add_chunk(test_project, text="some content")
    sem = [{"chunk_id": cid, "similarity": 0.72}]
    result = _retrieve(test_project, "content", mock_search_return=sem)
    assert result.chunk_hits[0].similarity == pytest.approx(0.72)


def test_chunk_hit_text_populated(test_project):
    cid = _add_chunk(test_project, text="I prefer Python development")
    sem = [{"chunk_id": cid, "similarity": 0.8}]
    result = _retrieve(test_project, "Python", mock_search_return=sem)
    assert result.chunk_hits[0].text == "I prefer Python development"


def test_top_k_passed_to_embedding_service(test_project):
    import app.services.retrieval_service as svc
    mock_emb = MagicMock()
    mock_emb.search.return_value = []
    original = svc.embedding_service
    svc.embedding_service = mock_emb
    try:
        from app.services.retrieval_service import retrieve
        retrieve(test_project, "query", top_k=3)
        mock_emb.search.assert_called_once()
        _, kwargs = mock_emb.search.call_args
        assert kwargs.get("top_k") == 3
    finally:
        svc.embedding_service = original


def test_unknown_chunk_id_from_semantic_excluded(test_project):
    """If embedding search returns a chunk_id not in the project DB, skip it."""
    sem = [{"chunk_id": "c_doesnotexist", "similarity": 0.9}]
    result = _retrieve(test_project, "anything", mock_search_return=sem)
    assert result.chunk_hits == []


# ── Chunk scoring / ordering ───────────────────────────────────────────────────

def test_chunk_hits_sorted_by_score_descending(test_project):
    c1 = _add_chunk(test_project, text="low similarity chunk")
    c2 = _add_chunk(test_project, text="high similarity chunk")
    sem = [
        {"chunk_id": c1, "similarity": 0.5},
        {"chunk_id": c2, "similarity": 0.95},
    ]
    result = _retrieve(test_project, "chunk", mock_search_return=sem)
    assert len(result.chunk_hits) == 2
    assert result.chunk_hits[0].score >= result.chunk_hits[1].score


def test_recency_contributes_to_score(test_project):
    """A recent chunk should score higher than an old chunk with equal similarity."""
    old_time = utcnow() - timedelta(days=120)
    c_old = _add_chunk(test_project, text="old content about backend", created_at=old_time)
    c_new = _add_chunk(test_project, text="new content about backend")
    sem = [
        {"chunk_id": c_old, "similarity": 0.8},
        {"chunk_id": c_new, "similarity": 0.8},
    ]
    result = _retrieve(test_project, "backend", mock_search_return=sem)
    new_hit = next(h for h in result.chunk_hits if h.chunk_id == c_new)
    old_hit = next(h for h in result.chunk_hits if h.chunk_id == c_old)
    assert new_hit.score > old_hit.score


# ── Fact retrieval via key alias ─────────────────────────────────────────────

def test_query_my_name_hits_user_name_fact(test_project):
    _add_fact(test_project, key="user_name", value="Alice")
    result = _retrieve(test_project, "What is my name?")
    assert any(f.key == "user_name" for f in result.fact_hits)


def test_fact_hit_value_correct(test_project):
    _add_fact(test_project, key="user_name", value="Alice")
    result = _retrieve(test_project, "my name")
    fact = next(f for f in result.fact_hits if f.key == "user_name")
    assert fact.value == "Alice"


def test_matched_keys_populated(test_project):
    _add_fact(test_project, key="user_name", value="Alice")
    result = _retrieve(test_project, "who am i")
    assert "user_name" in result.matched_keys


def test_superseded_facts_excluded(test_project):
    """Only active facts should appear in fact_hits."""
    now = utcnow()
    with project_session(test_project) as s:
        s.add(MemoryFact(
            fact_id=new_id("f"),
            project_id=test_project,
            key="user_name",
            value_json="OldName",
            value_type="string",
            confidence=0.9,
            source_chunk_id=None,
            source_type="explicit_user_statement",
            version=1,
            status="superseded",
            created_at=now,
            updated_at=now,
        ))
    result = _retrieve(test_project, "my name")
    assert all(f.value != "OldName" for f in result.fact_hits)


# ── Cross-project isolation ───────────────────────────────────────────────────

def test_cross_project_chunk_isolation(test_project):
    """Chunks stored in project A must NOT appear in project B's retrieval."""
    import shutil
    import uuid
    from app.core.config import settings
    from app.db.models import Project
    from app.db.session import drop_project, project_session, registry_session

    pid_b = "tp_b_" + uuid.uuid4().hex[:8]
    with registry_session() as s:
        s.add(Project(id=pid_b, name=pid_b, description="",
                      created_at=utcnow(), config_json={}))
    with project_session(pid_b):
        pass

    try:
        cid_a = _add_chunk(test_project, text="project A private data")
        # Project B's embedding search returns project A's chunk ID (simulates
        # a rogue embedding result). The SQL join must filter it out.
        sem = [{"chunk_id": cid_a, "similarity": 0.99}]
        result = _retrieve(pid_b, "private data", mock_search_return=sem)
        assert result.chunk_hits == []
    finally:
        drop_project(pid_b)
        shutil.rmtree(settings.project_dir(pid_b), ignore_errors=True)
