"""Database sessions.

The registry DB holds the `projects` table globally.
Each project gets its own SQLite file under data/{project_id}/facts.db,
which is the core isolation guarantee. Engines are cached per project.
"""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.models import Base


def _ensure_dir(p: Path) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)


# --- Registry (global) ---

_registry_engine: Engine | None = None
_RegistrySession: sessionmaker | None = None


def _registry() -> sessionmaker:
    global _registry_engine, _RegistrySession
    if _RegistrySession is None:
        path = settings.registry_db_path
        _ensure_dir(path)
        _registry_engine = create_engine(
            f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(_registry_engine, tables=[Base.metadata.tables["projects"]])
        _RegistrySession = sessionmaker(bind=_registry_engine, expire_on_commit=False, future=True)
    return _RegistrySession


@contextmanager
def registry_session() -> Iterator[Session]:
    s = _registry()()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


# --- Per-project engines ---

_project_engines: dict[str, Engine] = {}
_project_sessions: dict[str, sessionmaker] = {}

_PROJECT_TABLES = [
    Base.metadata.tables["memory_chunks"],
    Base.metadata.tables["memory_facts"],
    Base.metadata.tables["memory_conflicts"],
    Base.metadata.tables["memory_events"],
]


def _project_sessionmaker(project_id: str) -> sessionmaker:
    if project_id not in _project_sessions:
        path = settings.project_facts_db(project_id)
        _ensure_dir(path)
        engine = create_engine(
            f"sqlite:///{path}", future=True, connect_args={"check_same_thread": False}
        )
        Base.metadata.create_all(engine, tables=_PROJECT_TABLES)
        _project_engines[project_id] = engine
        _project_sessions[project_id] = sessionmaker(
            bind=engine, expire_on_commit=False, future=True
        )
    return _project_sessions[project_id]


@contextmanager
def project_session(project_id: str) -> Iterator[Session]:
    s = _project_sessionmaker(project_id)()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()


def drop_project(project_id: str) -> None:
    """Close cached engine for a project (used before filesystem deletion)."""
    eng = _project_engines.pop(project_id, None)
    _project_sessions.pop(project_id, None)
    if eng is not None:
        eng.dispose()
