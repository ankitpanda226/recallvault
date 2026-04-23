"""Unit tests for response_guard.compose().

All tests are pure: they build RetrievalResult objects in-process and assert
on the returned GuardedAnswer. No DB, no embeddings, no network.
"""
from __future__ import annotations

from datetime import datetime

import pytest

from app.services.response_guard import compose
from app.services.retrieval_service import ChunkHit, FactHit, RetrievalResult

_NOW = datetime(2026, 4, 23, 12, 0, 0)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _fact(confidence=0.9, key="user_name", value="Alice", updated_at=_NOW):
    return FactHit(
        fact_id="f_test001",
        key=key,
        value=value,
        value_type="string",
        confidence=confidence,
        version=1,
        source_chunk_id="c_test001",
        source_type="explicit_user_statement",
        created_at=_NOW,
        updated_at=updated_at,
        match_reason=f"exact key match on '{key}'",
    )


def _chunk(text="I prefer backend roles.", similarity=0.8):
    return ChunkHit(
        chunk_id="c_test001",
        text=text,
        speaker="user",
        created_at=_NOW,
        similarity=similarity,
    )


def _result(query="What is my name?", facts=(), chunks=(), keys=()):
    return RetrievalResult(
        query=query,
        project_id="test_proj",
        fact_hits=list(facts),
        chunk_hits=list(chunks),
        matched_keys=list(keys),
    )


# ── Verified mode ─────────────────────────────────────────────────────────────

def test_verified_high_confidence_fact():
    ans = compose(_result(facts=[_fact(confidence=0.9)]))
    assert ans.mode == "verified"


def test_verified_answer_contains_key_and_value():
    ans = compose(_result(facts=[_fact(key="user_name", value="Alice")]))
    assert "user name" in ans.answer
    assert "Alice" in ans.answer


def test_verified_provenance_populated():
    ans = compose(_result(facts=[_fact()]))
    assert len(ans.provenance) == 1
    assert ans.provenance[0].fact_id == "f_test001"
    assert ans.provenance[0].source_chunk_id == "c_test001"


def test_verified_supporting_chunks_populated():
    ans = compose(_result(facts=[_fact()]))
    assert "c_test001" in ans.supporting_chunks


def test_verified_takes_priority_over_chunk():
    """When both a qualifying fact and a chunk exist, mode must be verified."""
    ans = compose(_result(
        query="my name please",
        facts=[_fact(confidence=0.9)],
        chunks=[_chunk(text="my name is Alice", similarity=0.9)],
    ))
    assert ans.mode == "verified"


def test_verified_at_exact_threshold():
    """Confidence equal to threshold (0.75) qualifies."""
    ans = compose(_result(facts=[_fact(confidence=0.75)]))
    assert ans.mode == "verified"


def test_below_confidence_threshold_not_verified():
    """Fact with confidence 0.74 must NOT produce verified."""
    ans = compose(_result(
        query="favorite color",
        facts=[_fact(confidence=0.74)],
    ))
    assert ans.mode != "verified"


# ── Cautious mode ─────────────────────────────────────────────────────────────

def test_cautious_with_lexical_overlap():
    """Chunk above similarity floor + query token in chunk text → cautious."""
    ans = compose(_result(
        query="backend engineer roles",
        chunks=[_chunk(text="I prefer backend engineer roles.", similarity=0.8)],
    ))
    assert ans.mode == "cautious"


def test_cautious_answer_contains_chunk_snippet():
    text = "I prefer backend engineer roles."
    ans = compose(_result(
        query="backend engineer roles",
        chunks=[_chunk(text=text, similarity=0.8)],
    ))
    assert text in ans.answer


def test_cautious_long_chunk_truncated_to_240():
    long_text = "backend " + ("x" * 300)
    ans = compose(_result(
        query="backend details",
        chunks=[_chunk(text=long_text, similarity=0.8)],
    ))
    assert ans.mode == "cautious"
    assert "..." in ans.answer


def test_cautious_supporting_chunks_populated():
    ans = compose(_result(
        query="backend engineer roles",
        chunks=[_chunk(text="backend roles are great", similarity=0.8)],
    ))
    assert ans.mode == "cautious"
    assert len(ans.supporting_chunks) > 0


# ── Abstain mode ──────────────────────────────────────────────────────────────

def test_abstain_empty_retrieval():
    ans = compose(_result())
    assert ans.mode == "abstain"


def test_abstain_chunk_below_similarity_floor():
    """Chunk with similarity 0.3 (below 0.45 floor) must produce abstain."""
    ans = compose(_result(
        query="backend roles",
        chunks=[_chunk(text="backend roles", similarity=0.3)],
    ))
    assert ans.mode == "abstain"


def test_abstain_no_lexical_overlap():
    """High similarity chunk that shares zero content tokens → abstain."""
    ans = compose(_result(
        query="backend engineer",          # tokens: {backend, engineer}
        chunks=[_chunk(text="I like apples and oranges.", similarity=0.8)],
    ))
    assert ans.mode == "abstain"


def test_abstain_stopwords_only_query():
    """All content-bearing tokens are stopwords → query_tokens empty → abstain."""
    # "what", "that", "with", "them" are all in _STOPWORDS
    ans = compose(_result(
        query="what is that with them",
        chunks=[_chunk(text="what is that with them indeed", similarity=0.8)],
    ))
    assert ans.mode == "abstain"


def test_abstain_answer_does_not_leak_chunk_content():
    chunk_text = "secret information about user preferences"
    ans = compose(_result(
        query="favorite color",
        chunks=[_chunk(text=chunk_text, similarity=0.3)],
    ))
    assert ans.mode == "abstain"
    assert chunk_text not in ans.answer


def test_abstain_provenance_empty():
    ans = compose(_result())
    assert ans.provenance == []
    assert ans.supporting_chunks == []


def test_abstain_when_no_fact_and_no_qualifying_chunk():
    """Below-threshold fact + below-floor chunk → abstain."""
    ans = compose(_result(
        query="what color is this",
        facts=[_fact(confidence=0.5)],
        chunks=[_chunk(text="color", similarity=0.2)],
    ))
    assert ans.mode == "abstain"
