"""Shared pytest fixtures for RecallVault unit tests.

RV_STORAGE_ROOT is set at module level (before any app module is imported)
so that the settings singleton picks up the temp dir on first instantiation.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid

import pytest

# ── Must come before any app import ──────────────────────────────────────────
_TEST_STORAGE = tempfile.mkdtemp(prefix="rv_test_")
os.environ.setdefault("RV_STORAGE_ROOT", _TEST_STORAGE)


@pytest.fixture(scope="session", autouse=True)
def _cleanup_storage():
    """Remove the shared temp storage tree after the full test session."""
    yield
    shutil.rmtree(_TEST_STORAGE, ignore_errors=True)


@pytest.fixture
def test_project():
    """Create an isolated RecallVault project; tear it down after the test."""
    from app.core.config import settings
    from app.db.models import Project
    from app.db.session import drop_project, project_session, registry_session
    from app.utils.time import utcnow

    pid = "tp_" + uuid.uuid4().hex[:8]

    with registry_session() as s:
        s.add(Project(
            id=pid, name=pid, description="",
            created_at=utcnow(), config_json={},
        ))

    with project_session(pid):
        pass  # ensures all project tables are created

    yield pid

    drop_project(pid)
    shutil.rmtree(settings.project_dir(pid), ignore_errors=True)


@pytest.fixture
def mem_session():
    """In-memory SQLite session with all per-project tables — for unit tests
    that exercise DB logic directly without the project-session machinery."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.models import Base

    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()
