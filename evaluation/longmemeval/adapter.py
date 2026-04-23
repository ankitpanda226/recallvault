"""RecallVault adapter for a single LongMemEval question.

Caller (run.py) is responsible for setting RV_STORAGE_ROOT (and optionally
RV_EMBEDDING_MODEL) before importing this module, so that Settings picks up
the right values.

Public API:
    run_question(entry, window=1, overlap=0) -> QuestionResult
"""
from __future__ import annotations

import gc
import hashlib
import shutil
from dataclasses import dataclass, field
from typing import Generator


@dataclass
class QuestionResult:
    question_id: str
    question_type: str
    gold_session_ids: list[str]
    retrieved_session_ids: list[str]
    hit: bool
    retrieved_chunk_ids: list[str] = field(default_factory=list)


def _project_id(question_id: str) -> str:
    """Stable short project ID derived from the question ID."""
    return "lme_" + hashlib.md5(question_id.encode()).hexdigest()[:12]


def _windowed_chunks(
    turns: list[dict], window: int, overlap: int
) -> Generator[str, None, None]:
    """Yield text chunks from a session's turns using a sliding window.

    Each chunk is N consecutive turns joined as "role: content" lines.
    The window advances by (window - overlap) turns each step.
    A session with fewer turns than the window produces one chunk.
    """
    if not turns:
        return
    step = max(1, window - overlap)
    i = 0
    while i < len(turns):
        chunk_turns = turns[i : i + window]
        lines = [
            f"{t.get('role', 'user')}: {t.get('content', '').strip()}"
            for t in chunk_turns
            if t.get("content", "").strip()
        ]
        if lines:
            yield "\n".join(lines)
        if i + window >= len(turns):
            break
        i += step


def run_question(entry: dict, window: int = 1, overlap: int = 0) -> QuestionResult:
    """Ingest one LongMemEval entry into a fresh project and retrieve top-5."""
    # Import here so caller can set RV_STORAGE_ROOT before any app module loads.
    from app.core.config import settings
    from app.db.models import MemoryChunk, Project
    from app.db.session import project_session, registry_session
    from app.services import embedding_service, ingest_service, retrieval_service
    from app.utils.time import utcnow

    question_id: str = entry["question_id"]
    question_type: str = entry["question_type"]
    question: str = entry["question"]
    gold_session_ids: list[str] = entry["answer_session_ids"]

    # haystack_session_ids[i] is the session ID for haystack_sessions[i]
    haystack_session_ids: list[str] = entry["haystack_session_ids"]
    haystack_sessions: list[list[dict]] = entry["haystack_sessions"]

    project_id = _project_id(question_id)

    # --- Create project ---
    with registry_session() as s:
        if s.query(Project).filter(Project.id == project_id).first() is None:
            s.add(Project(
                id=project_id, name=project_id, description="",
                created_at=utcnow(), config_json={},
            ))
    with project_session(project_id):
        pass

    try:
        # --- Ingest all sessions ---
        for session_id, turns in zip(haystack_session_ids, haystack_sessions):
            if window <= 1:
                # Default: one chunk per turn.
                for turn in turns:
                    role = turn.get("role", "user")
                    content = turn.get("content", "").strip()
                    if not content:
                        continue
                    speaker = "user" if role == "user" else "assistant"
                    ingest_service.ingest(
                        project_id, content, speaker=speaker, tags=[session_id],
                    )
            else:
                # Sliding-window: N consecutive turns per chunk, step = window - overlap.
                # All windows share the session's tag for session-ID recovery.
                # Speaker is always "user" so fact extraction isn't skipped; for
                # retrieval benchmarking the extraction output doesn't affect scoring.
                for chunk_text in _windowed_chunks(turns, window, overlap):
                    ingest_service.ingest(
                        project_id, chunk_text, speaker="user", tags=[session_id],
                    )

        # --- Retrieve top-5 ---
        result = retrieval_service.retrieve(project_id, question, top_k=5)
        retrieved_chunk_ids = [c.chunk_id for c in result.chunk_hits]

        # --- Map chunk IDs → session IDs via tags_json ---
        retrieved_session_ids: list[str] = []
        if retrieved_chunk_ids:
            with project_session(project_id) as sess:
                rows = (
                    sess.query(MemoryChunk)
                    .filter(
                        MemoryChunk.project_id == project_id,
                        MemoryChunk.chunk_id.in_(retrieved_chunk_ids),
                    )
                    .all()
                )
                seen: set[str] = set()
                # Preserve retrieval order for the session list.
                chunk_to_sessions: dict[str, list[str]] = {
                    r.chunk_id: r.tags_json for r in rows
                }
                for cid in retrieved_chunk_ids:
                    for sid in chunk_to_sessions.get(cid, []):
                        if sid not in seen:
                            seen.add(sid)
                            retrieved_session_ids.append(sid)

        hit = bool(set(gold_session_ids) & set(retrieved_session_ids))

        return QuestionResult(
            question_id=question_id,
            question_type=question_type,
            gold_session_ids=gold_session_ids,
            retrieved_session_ids=retrieved_session_ids,
            hit=hit,
            retrieved_chunk_ids=retrieved_chunk_ids,
        )

    finally:
        # --- Cleanup: release engine, client, then delete data directory ---
        from app.db.session import drop_project
        project_dir = settings.project_dir(project_id)
        drop_project(project_id)              # closes SQLAlchemy engine
        embedding_service._client_for.cache_clear()  # releases ChromaDB client
        gc.collect()
        shutil.rmtree(project_dir, ignore_errors=True)
