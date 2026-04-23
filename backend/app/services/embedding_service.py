"""Embedding service.

Uses sentence-transformers locally so the demo works with no API key.
Each project gets its own Chroma collection, persisted under
data/{project_id}/vector_store/. This enforces vector-level isolation.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import os
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

# posthog ≥7 changed capture(distinct_id, event, props) → capture(event, **kw).
# Chromadb 0.5 still uses the old 3-arg call, which raises TypeError before the
# posthog.disabled flag can suppress it. Patch capture to a no-op here, before
# chromadb imports posthog, so telemetry calls become silent regardless of version.
import posthog as _ph
_ph.capture = lambda *_: None  # type: ignore[attr-defined]
del _ph

import chromadb
from chromadb.config import Settings as ChromaSettings

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# Lazy-loaded embedding model
_model = None


def _get_model():
    global _model
    if _model is None:
        # Import here so startup is fast even if the service isn't used yet.
        from sentence_transformers import SentenceTransformer
        log.info("loading embedding model: %s", settings.embedding_model)
        _model = SentenceTransformer(settings.embedding_model)
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    vecs = model.encode(texts, convert_to_numpy=True, normalize_embeddings=True)
    return [v.tolist() for v in vecs]


@lru_cache(maxsize=64)
def _client_for(project_id: str) -> chromadb.PersistentClient:
    vec_dir: Path = settings.project_vector_dir(project_id)
    vec_dir.mkdir(parents=True, exist_ok=True)
    return chromadb.PersistentClient(
        path=str(vec_dir),
        settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False),
    )


def _collection(project_id: str):
    client = _client_for(project_id)
    return client.get_or_create_collection(
        name="chunks",
        metadata={"hnsw:space": "cosine"},
    )


def add_chunk(
    project_id: str,
    chunk_id: str,
    text: str,
    metadata: dict[str, Any],
) -> None:
    vec = embed([text])[0]
    col = _collection(project_id)
    col.upsert(
        ids=[chunk_id],
        embeddings=[vec],
        documents=[text],
        metadatas=[{k: v for k, v in metadata.items() if isinstance(v, (str, int, float, bool))}],
    )


def search(project_id: str, query: str, top_k: int = 5) -> list[dict[str, Any]]:
    col = _collection(project_id)
    if col.count() == 0:
        return []
    q_vec = embed([query])[0]
    res = col.query(query_embeddings=[q_vec], n_results=min(top_k, col.count()))
    out: list[dict[str, Any]] = []
    ids = res.get("ids", [[]])[0]
    docs = res.get("documents", [[]])[0]
    dists = res.get("distances", [[]])[0]
    metas = res.get("metadatas", [[]])[0]
    for cid, doc, dist, meta in zip(ids, docs, dists, metas):
        # Chroma cosine distance in [0, 2]; similarity in [-1, 1]. Normalize to [0, 1].
        sim = max(0.0, 1.0 - (dist / 2.0))
        out.append(
            {
                "chunk_id": cid,
                "text": doc,
                "similarity": sim,
                "metadata": meta or {},
            }
        )
    return out


def delete_chunk(project_id: str, chunk_id: str) -> None:
    col = _collection(project_id)
    col.delete(ids=[chunk_id])
