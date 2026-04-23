"""Unit tests for ingest_service.ingest().

embedding_service is patched to a no-op so tests require no ChromaDB instance
or model downloads. DB interactions use the real SQLite-backed test_project.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.db.models import MemoryChunk, MemoryFact
from app.db.session import project_session


def _ingest(project_id, text, speaker="user", tags=None):
    from app.services.ingest_service import ingest
    return ingest(project_id, text, speaker=speaker, tags=tags)


@pytest.fixture(autouse=True)
def _no_embedding(monkeypatch):
    """Prevent any real ChromaDB / model calls for every test in this module."""
    import app.services.ingest_service as svc
    monkeypatch.setattr(svc, "embedding_service", MagicMock(add_chunk=lambda **_: None))


# ── Chunk storage ─────────────────────────────────────────────────────────────

def test_single_short_message_one_chunk(test_project):
    report = _ingest(test_project, "My name is Alice.")
    assert len(report.chunk_ids) == 1


def test_empty_text_returns_empty_report(test_project):
    report = _ingest(test_project, "")
    assert report.chunk_ids == []
    assert report.candidates == 0


def test_whitespace_only_returns_empty_report(test_project):
    report = _ingest(test_project, "   \n  ")
    assert report.chunk_ids == []


def test_long_message_produces_multiple_chunks(test_project):
    # Build a text longer than the 600-char chunk threshold.
    sentence = "This is a sentence about something interesting. "
    text = sentence * 20          # ~960 chars
    report = _ingest(test_project, text)
    assert len(report.chunk_ids) > 1


def test_chunk_ids_are_unique(test_project):
    sentence = "This is a sentence about something interesting. "
    text = sentence * 20
    report = _ingest(test_project, text)
    assert len(set(report.chunk_ids)) == len(report.chunk_ids)


def test_chunks_persisted_in_db(test_project):
    report = _ingest(test_project, "My name is Alice.")
    with project_session(test_project) as s:
        rows = (
            s.query(MemoryChunk)
            .filter(MemoryChunk.chunk_id.in_(report.chunk_ids))
            .all()
        )
    assert len(rows) == len(report.chunk_ids)


def test_speaker_persisted(test_project):
    report = _ingest(test_project, "I prefer backend roles.", speaker="user")
    with project_session(test_project) as s:
        row = s.query(MemoryChunk).filter_by(chunk_id=report.chunk_ids[0]).first()
    assert row.speaker == "user"


def test_tags_persisted(test_project):
    tags = ["session_abc", "topic_career"]
    report = _ingest(test_project, "I prefer backend roles.", tags=tags)
    with project_session(test_project) as s:
        row = s.query(MemoryChunk).filter_by(chunk_id=report.chunk_ids[0]).first()
    assert row.tags_json == tags


def test_no_tags_defaults_to_empty_list(test_project):
    report = _ingest(test_project, "My name is Alice.")
    with project_session(test_project) as s:
        row = s.query(MemoryChunk).filter_by(chunk_id=report.chunk_ids[0]).first()
    assert row.tags_json == []


# ── Fact extraction ───────────────────────────────────────────────────────────

def test_known_pattern_extracts_and_stores_fact(test_project):
    report = _ingest(test_project, "My name is Alice.")
    assert report.accepted >= 1
    names = [f for f in report.facts if f.key == "user_name"]
    assert names, "Expected at least one user_name fact"
    assert names[0].action in ("inserted", "no_op", "superseded")


def test_fact_persisted_in_db(test_project):
    _ingest(test_project, "My name is Alice.")
    with project_session(test_project) as s:
        fact = (
            s.query(MemoryFact)
            .filter_by(project_id=test_project, key="user_name", status="active")
            .first()
        )
    assert fact is not None
    assert "Alice" in str(fact.value_json)


def test_assistant_speaker_skips_fact_extraction(test_project):
    report = _ingest(
        test_project,
        "I see that your name is Alice.",
        speaker="assistant",
    )
    assert report.candidates == 0
    assert report.accepted == 0


def test_unknown_text_no_facts(test_project):
    report = _ingest(test_project, "The weather is lovely today.")
    assert report.candidates == 0


def test_report_counts_consistent(test_project):
    report = _ingest(test_project, "My name is Alice.")
    assert report.accepted + report.rejected == report.candidates


def test_second_ingest_same_fact_noop(test_project):
    _ingest(test_project, "My name is Alice.")
    report2 = _ingest(test_project, "My name is Alice.")
    if report2.facts:
        assert report2.facts[0].action == "no_op"


# ── ingest_session() tests ────────────────────────────────────────────────────

_TURNS = [
    ("user", "Hello, how are you?"),
    ("assistant", "I'm doing well, thanks!"),
    ("user", "My name is Alice and I prefer backend roles."),
    ("assistant", "Nice to meet you, Alice!"),
    ("user", "I graduate in May 2027."),
]


def test_ingest_session_per_turn_mode(test_project, monkeypatch):
    import app.services.ingest_service as svc
    monkeypatch.setattr(svc, "embedding_service", MagicMock(add_chunk=lambda **_: None))
    monkeypatch.setattr(svc.settings, "chunk_mode", "per_turn")

    from app.services.ingest_service import ingest_session
    report = ingest_session(test_project, "sess_A", _TURNS)
    # 3 user turns + 2 assistant turns = 5 non-empty turns → 5 chunks
    assert len(report.chunk_ids) == 5


def test_ingest_session_per_session_mode(test_project, monkeypatch):
    import app.services.ingest_service as svc
    monkeypatch.setattr(svc, "embedding_service", MagicMock(add_chunk=lambda **_: None))
    monkeypatch.setattr(svc.settings, "chunk_mode", "per_session")

    from app.services.ingest_service import ingest_session
    report = ingest_session(test_project, "sess_B", _TURNS)
    # All turns joined into one chunk
    assert len(report.chunk_ids) == 1


def test_ingest_session_sliding_window_mode(test_project, monkeypatch):
    import app.services.ingest_service as svc
    monkeypatch.setattr(svc, "embedding_service", MagicMock(add_chunk=lambda **_: None))
    monkeypatch.setattr(svc.settings, "chunk_mode", "sliding_window")
    monkeypatch.setattr(svc.settings, "chunk_window_size", 3)
    monkeypatch.setattr(svc.settings, "chunk_overlap", 1)

    from app.services.ingest_service import ingest_session
    # 5 turns, window=3, overlap=1 → step=2 → windows at [0,3), [2,5) → 2 chunks
    report = ingest_session(test_project, "sess_C", _TURNS)
    assert len(report.chunk_ids) == 2


def test_ingest_session_preserves_session_id_tag(test_project, monkeypatch):
    import app.services.ingest_service as svc
    monkeypatch.setattr(svc, "embedding_service", MagicMock(add_chunk=lambda **_: None))
    monkeypatch.setattr(svc.settings, "chunk_mode", "per_turn")

    from app.services.ingest_service import ingest_session
    from app.db.models import MemoryChunk

    sid = "sess_tag_test"
    report = ingest_session(test_project, sid, _TURNS)
    with project_session(test_project) as s:
        rows = (
            s.query(MemoryChunk)
            .filter(MemoryChunk.chunk_id.in_(report.chunk_ids))
            .all()
        )
    assert all(sid in row.tags_json for row in rows)


def test_ingest_session_backward_compatible(test_project, monkeypatch):
    """ingest() without session_id behaves identically to before."""
    import app.services.ingest_service as svc
    monkeypatch.setattr(svc, "embedding_service", MagicMock(add_chunk=lambda **_: None))

    report = _ingest(test_project, "My name is Alice.")
    assert len(report.chunk_ids) == 1
    assert report.accepted >= 1
