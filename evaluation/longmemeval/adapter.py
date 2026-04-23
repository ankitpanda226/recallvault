"""RecallVault adapter for a single LongMemEval question.

Caller (run.py) is responsible for setting RV_STORAGE_ROOT,
RV_EMBEDDING_MODEL, and RV_CHUNK_MODE (+ window/overlap vars) before
importing this module, so that Settings picks up the right values.

Public API:
    run_question(entry) -> QuestionResult
"""
from __future__ import annotations

import gc
import hashlib
import shutil
from dataclasses import dataclass, field


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


def run_question(entry: dict) -> QuestionResult:
    """Ingest one LongMemEval entry into a fresh project and retrieve top-5.

    Chunking strategy is controlled entirely by settings.chunk_mode
    (RV_CHUNK_MODE env var). The caller sets the env var before importing;
    ingest_session() reads settings at call time.
    """
    from app.core.config import settings
    from app.db.models import MemoryChunk, Project
    from app.db.session import drop_project, project_session, registry_session
    from app.services import embedding_service, ingest_service, retrieval_service
    from app.utils.time import utcnow

    question_id: str = entry["question_id"]
    question_type: str = entry["question_type"]
    question: str = entry["question"]
    gold_session_ids: list[str] = entry["answer_session_ids"]

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
        # --- Ingest all sessions via ingest_session() ---
        for session_id, turns_raw in zip(haystack_session_ids, haystack_sessions):
            turns = [
                (t.get("role", "user"), t.get("content", ""))
                for t in turns_raw
            ]
            ingest_service.ingest_session(
                project_id=project_id,
                session_id=session_id,
                turns=turns,
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
        project_dir = settings.project_dir(project_id)
        drop_project(project_id)
        embedding_service._client_for.cache_clear()
        gc.collect()
        shutil.rmtree(project_dir, ignore_errors=True)
