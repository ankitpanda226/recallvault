"""Unit tests for conflict_resolver.resolve_and_store().

Uses an in-memory SQLite session (mem_session fixture from conftest) so
there's no filesystem involvement and each test starts from a clean slate.
"""
from __future__ import annotations

import pytest

from app.db.models import MemoryFact
from app.services.conflict_resolver import resolve_and_store


def _store(session, key, value, pid="proj1", confidence=0.9, version_check=None):
    return resolve_and_store(
        session=session,
        project_id=pid,
        key=key,
        value=value,
        value_type="string",
        confidence=confidence,
        source_chunk_id=None,
        source_type="explicit_user_statement",
    )


# ── First write ───────────────────────────────────────────────────────────────

def test_first_write_creates_version_1(mem_session):
    outcome = _store(mem_session, "user_name", "Alice")
    assert outcome.action == "inserted"
    assert outcome.version == 1
    assert outcome.previous_fact_id is None


def test_first_write_fact_is_active(mem_session):
    outcome = _store(mem_session, "user_name", "Alice")
    mem_session.flush()
    row = mem_session.query(MemoryFact).filter_by(fact_id=outcome.fact_id).first()
    assert row is not None
    assert row.status == "active"
    assert row.version == 1


def test_first_write_stores_correct_value(mem_session):
    _store(mem_session, "graduation_date", "May 2027")
    mem_session.flush()
    row = (
        mem_session.query(MemoryFact)
        .filter_by(project_id="proj1", key="graduation_date", status="active")
        .first()
    )
    assert row.value_json == "May 2027"


# ── Idempotent re-write ───────────────────────────────────────────────────────

def test_identical_rewrite_is_noop(mem_session):
    _store(mem_session, "user_name", "Alice")
    mem_session.flush()
    outcome2 = _store(mem_session, "user_name", "Alice")
    assert outcome2.action == "no_op"
    assert outcome2.version == 1


def test_noop_does_not_create_second_row(mem_session):
    _store(mem_session, "user_name", "Alice")
    _store(mem_session, "user_name", "Alice")
    mem_session.flush()
    rows = mem_session.query(MemoryFact).filter_by(project_id="proj1", key="user_name").all()
    assert len(rows) == 1


def test_noop_strengthens_confidence(mem_session):
    _store(mem_session, "user_name", "Alice", confidence=0.8)
    mem_session.flush()
    _store(mem_session, "user_name", "Alice", confidence=0.95)
    mem_session.flush()
    row = (
        mem_session.query(MemoryFact)
        .filter_by(project_id="proj1", key="user_name", status="active")
        .first()
    )
    assert row.confidence == pytest.approx(0.95)


def test_case_insensitive_equivalent(mem_session):
    """Resolver treats 'Alice' and 'alice' as equivalent (no new version)."""
    _store(mem_session, "user_name", "Alice")
    mem_session.flush()
    outcome = _store(mem_session, "user_name", "alice")
    assert outcome.action == "no_op"


# ── Conflict / supersede ──────────────────────────────────────────────────────

def test_different_value_supersedes_old(mem_session):
    _store(mem_session, "user_name", "Alice")
    mem_session.flush()
    outcome = _store(mem_session, "user_name", "Bob")
    assert outcome.action == "superseded"
    assert outcome.version == 2


def test_supersede_old_fact_marked_superseded(mem_session):
    first = _store(mem_session, "user_name", "Alice")
    mem_session.flush()
    _store(mem_session, "user_name", "Bob")
    mem_session.flush()
    old_row = mem_session.query(MemoryFact).filter_by(fact_id=first.fact_id).first()
    assert old_row.status == "superseded"


def test_supersede_new_fact_is_active(mem_session):
    _store(mem_session, "user_name", "Alice")
    mem_session.flush()
    outcome2 = _store(mem_session, "user_name", "Bob")
    mem_session.flush()
    new_row = mem_session.query(MemoryFact).filter_by(fact_id=outcome2.fact_id).first()
    assert new_row.status == "active"
    assert new_row.value_json == "Bob"


def test_history_preserved_across_versions(mem_session):
    """After two supersedes there are three rows, all with different versions."""
    _store(mem_session, "user_name", "Alice")
    mem_session.flush()
    _store(mem_session, "user_name", "Bob")
    mem_session.flush()
    _store(mem_session, "user_name", "Carol")
    mem_session.flush()
    rows = (
        mem_session.query(MemoryFact)
        .filter_by(project_id="proj1", key="user_name")
        .order_by(MemoryFact.version)
        .all()
    )
    assert len(rows) == 3
    assert [r.version for r in rows] == [1, 2, 3]
    assert rows[-1].status == "active"
    assert all(r.status == "superseded" for r in rows[:-1])


# ── Soft-delete (forget) ──────────────────────────────────────────────────────

def test_deleted_status_preserves_history(mem_session):
    """Marking a fact deleted keeps the row; no active fact remains."""
    from app.utils.time import utcnow

    outcome = _store(mem_session, "user_name", "Alice")
    mem_session.flush()

    row = mem_session.query(MemoryFact).filter_by(fact_id=outcome.fact_id).first()
    row.status = "deleted"
    row.updated_at = utcnow()
    mem_session.flush()

    all_rows = mem_session.query(MemoryFact).filter_by(
        project_id="proj1", key="user_name"
    ).all()
    assert len(all_rows) == 1
    assert all_rows[0].status == "deleted"

    active = mem_session.query(MemoryFact).filter_by(
        project_id="proj1", key="user_name", status="active"
    ).first()
    assert active is None


# ── Project isolation via key namespace ───────────────────────────────────────

def test_same_key_different_projects_independent(mem_session):
    """Resolving the same key in two projects creates independent v1 facts."""
    o1 = _store(mem_session, "user_name", "Alice", pid="proj_a")
    mem_session.flush()
    o2 = _store(mem_session, "user_name", "Bob", pid="proj_b")
    mem_session.flush()
    assert o1.action == "inserted"
    assert o2.action == "inserted"
    assert o1.version == 1
    assert o2.version == 1
