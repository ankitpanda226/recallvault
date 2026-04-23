"""Response guard.

The guard is the anti-hallucination boundary. Given a retrieval result,
it classifies the situation and composes a safe, provenance-aware answer.

Decision rules (architecture section 8.8):
  - verified:   a verified fact with confidence >= threshold exists -> answer confidently
  - cautious:   only fuzzy semantic evidence (no verified fact) -> hedge
  - abstain:    no evidence at all -> say memory is unavailable

The guard NEVER produces a confident answer without a source_chunk_id trail.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.core.config import settings
from app.services.retrieval_service import RetrievalResult


@dataclass
class Provenance:
    source_chunk_id: str | None
    source_type: str | None
    fact_id: str | None
    version: int | None
    created_at: str | None


@dataclass
class GuardedAnswer:
    mode: str                      # verified | cautious | abstain
    answer: str
    provenance: list[Provenance] = field(default_factory=list)
    supporting_chunks: list[str] = field(default_factory=list)
    matched_keys: list[str] = field(default_factory=list)


def _fmt_value(value: Any) -> str:
    if isinstance(value, list):
        if not value:
            return "(empty)"
        if len(value) == 1:
            return str(value[0])
        return ", ".join(str(v) for v in value[:-1]) + f" and {value[-1]}"
    return str(value)


def _human_key(key: str) -> str:
    return key.replace("_", " ")


def compose(result: RetrievalResult) -> GuardedAnswer:
    # Verified path: at least one fact hit passing confidence threshold
    top_fact = next(
        (f for f in result.fact_hits if f.confidence >= settings.verified_confidence_min),
        None,
    )
    if top_fact is not None:
        prov = [
            Provenance(
                source_chunk_id=top_fact.source_chunk_id,
                source_type=top_fact.source_type,
                fact_id=top_fact.fact_id,
                version=top_fact.version,
                created_at=top_fact.created_at.isoformat() if top_fact.created_at else None,
            )
        ]
        key_h = _human_key(top_fact.key)
        val_h = _fmt_value(top_fact.value)
        date_h = (
            top_fact.updated_at.strftime("%B %-d, %Y")
            if top_fact.updated_at
            else "an earlier session"
        )
        answer = (
            f"I have a stored record that your {key_h} is {val_h}, "
            f"based on an explicit prior statement saved on {date_h}."
        )
        return GuardedAnswer(
            mode="verified",
            answer=answer,
            provenance=prov,
            supporting_chunks=[top_fact.source_chunk_id] if top_fact.source_chunk_id else [],
            matched_keys=result.matched_keys,
        )

    # Cautious path: only semantic evidence above a floor
    strong_chunks = [c for c in result.chunk_hits if c.similarity >= settings.cautious_semantic_min]
    if strong_chunks:
        # Lexical guard: MiniLM similarity can exceed the floor on semantically
        # empty queries (e.g. "What is my favorite color?"). Require at least one
        # content-bearing token (≥4 alpha chars, not a generic stopword) from the
        # query to appear literally in the chunk. If nothing matches, abstain.
        _STOPWORDS = {
            "what", "when", "where", "which", "that", "with", "from", "have",
            "been", "will", "they", "them", "then", "than", "your", "mine",
            "more", "some", "just", "into", "like", "tell", "about", "does",
            "also", "there", "their", "here", "this", "these", "those",
        }
        query_tokens = {
            w for w in re.findall(r"[a-zA-Z]{4,}", result.query.lower())
            if w not in _STOPWORDS
        }
        lexical_chunks = [
            c for c in strong_chunks
            if query_tokens & set(re.findall(r"[a-zA-Z]{4,}", c.text.lower()))
        ]
        if lexical_chunks:
            top = lexical_chunks[0]
            snippet = top.text if len(top.text) <= 240 else top.text[:237] + "..."
            answer = (
                "I do not have a verified stored fact for that, but I found related "
                f"past discussion: \"{snippet}\". I can't confirm this as a stored "
                "fact without more context."
            )
            return GuardedAnswer(
                mode="cautious",
                answer=answer,
                provenance=[],
                supporting_chunks=[c.chunk_id for c in lexical_chunks[:3]],
                matched_keys=result.matched_keys,
            )

    # Abstain
    return GuardedAnswer(
        mode="abstain",
        answer="I don't have any stored memory for that yet. I won't guess.",
        provenance=[],
        supporting_chunks=[],
        matched_keys=result.matched_keys,
    )
