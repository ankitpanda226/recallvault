"""Unit tests for fact_extractor.extract() and extract_rules().

Pure function tests — no DB, no network.
"""
from __future__ import annotations

import json

import pytest

from app.services.fact_extractor import CandidateFact, extract, extract_rules


# ── Known-pattern extraction ──────────────────────────────────────────────────

def test_extract_user_name():
    facts = extract_rules("My name is Alice.")
    keys = [f.key for f in facts]
    assert "user_name" in keys


def test_extract_user_name_value():
    facts = extract_rules("My name is Alice.")
    fact = next(f for f in facts if f.key == "user_name")
    assert fact.value == "Alice"
    assert fact.confidence >= 0.9
    assert fact.source_type == "explicit_user_statement"


def test_extract_preferred_roles_returns_list():
    facts = extract_rules("I prefer backend engineer roles.")
    fact = next((f for f in facts if f.key == "preferred_roles"), None)
    assert fact is not None
    assert isinstance(fact.value, list)
    assert "backend engineer" in fact.value[0]


def test_extract_graduation_date_month_year():
    facts = extract_rules("My expected graduation is May 2027.")
    fact = next((f for f in facts if f.key == "graduation_date"), None)
    assert fact is not None
    assert "May 2027" in fact.value


def test_extract_graduation_date_graduate_in():
    facts = extract_rules("I graduate in December 2026.")
    fact = next((f for f in facts if f.key == "graduation_date"), None)
    assert fact is not None
    assert "December 2026" in fact.value


def test_extract_response_style_concise():
    facts = extract_rules("I prefer concise answers.")
    fact = next((f for f in facts if f.key == "response_style_preference"), None)
    assert fact is not None
    assert "concise" in fact.value.lower()


def test_extract_architecture_decision_chose():
    facts = extract_rules("We chose Postgres for durable storage.")
    fact = next((f for f in facts if f.key == "architecture_decision"), None)
    assert fact is not None
    assert "Postgres" in fact.value


def test_extract_company_targets():
    facts = extract_rules("I'm targeting Google, Apple, and Meta.")
    fact = next((f for f in facts if f.key == "company_targets"), None)
    assert fact is not None
    assert isinstance(fact.value, list)
    assert len(fact.value) >= 2


def test_extract_bug_root_cause():
    facts = extract_rules("The root cause is a missing index on the users table.")
    fact = next((f for f in facts if f.key == "bug_root_cause"), None)
    assert fact is not None
    assert "index" in fact.value.lower()


# ── Unknown / irrelevant text ─────────────────────────────────────────────────

def test_irrelevant_text_returns_empty():
    facts = extract_rules("The weather is nice today.")
    assert facts == []


def test_empty_string_returns_empty():
    assert extract_rules("") == []


def test_short_noise_returns_empty():
    assert extract_rules("ok") == []


# ── Deduplication ─────────────────────────────────────────────────────────────

def test_extract_deduplicates_same_key_value():
    """Two sentences matching the same fact key+value produce one entry."""
    text = "My name is Alice. By the way, my name is Alice."
    facts = extract("My name is Alice. By the way, my name is Alice.")
    name_facts = [f for f in facts if f.key == "user_name"]
    assert len(name_facts) == 1


# ── LLM extraction path ───────────────────────────────────────────────────────

def test_llm_extraction_disabled_by_default():
    """With RV_LLM_EXTRACTION=false (default), extract() returns rule-based only."""
    from app.core.config import settings
    assert settings.llm_extraction is False


def test_extract_returns_candidate_fact_instances():
    facts = extract("My name is Bob.")
    assert all(isinstance(f, CandidateFact) for f in facts)


def test_extract_fact_has_required_fields():
    facts = extract("My name is Bob.")
    fact = next(f for f in facts if f.key == "user_name")
    assert fact.key
    assert fact.value
    assert fact.value_type in ("string", "list", "number", "bool")
    assert 0.0 <= fact.confidence <= 1.0
    assert fact.source_type
    assert fact.reason


# ── LLM extraction — fallback behaviour ──────────────────────────────────────

class TestLLMExtraction:
    def test_llm_not_called_when_flag_disabled(self, monkeypatch):
        import app.services.fact_extractor as fe
        from app.core.config import settings
        monkeypatch.setattr(settings, "llm_extraction", False)

        def must_not_call(text):
            raise AssertionError("extract_llm must not be called when flag is off")

        monkeypatch.setattr(fe, "extract_llm", must_not_call)
        facts = fe.extract("My name is Alice.")
        assert any(f.key == "user_name" for f in facts)

    def test_llm_not_called_when_rules_hit(self, monkeypatch):
        import app.services.fact_extractor as fe
        from app.core.config import settings
        monkeypatch.setattr(settings, "llm_extraction", True)

        def must_not_call(text):
            raise AssertionError("extract_llm must not be called when rules produce candidates")

        monkeypatch.setattr(fe, "extract_llm", must_not_call)
        facts = fe.extract("My name is Alice.")
        assert any(f.key == "user_name" for f in facts)

    def test_llm_called_when_rules_miss(self, monkeypatch):
        import app.services.fact_extractor as fe
        from app.core.config import settings
        from app.services.fact_extractor import CandidateFact
        monkeypatch.setattr(settings, "llm_extraction", True)

        fake = CandidateFact(
            key="user_hobby", value="hiking", value_type="string",
            confidence=0.85, source_type="explicit_user_statement",
            reason="user stated hobby",
        )
        monkeypatch.setattr(fe, "extract_llm", lambda t: [fake])
        facts = fe.extract("the weather is nice today")
        assert any(f.key == "user_hobby" for f in facts)

    def test_llm_graceful_when_ollama_unreachable(self, monkeypatch):
        import httpx
        from app.core.config import settings
        monkeypatch.setattr(settings, "llm_extraction", True)

        def raise_connect_error(*_a, **_kw):
            raise httpx.ConnectError("Connection refused")

        monkeypatch.setattr(httpx, "post", raise_connect_error)

        from app.services.fact_extractor import extract_llm
        assert extract_llm("I love hiking.") == []

    def test_llm_graceful_on_malformed_json(self, monkeypatch):
        import httpx
        from unittest.mock import MagicMock
        from app.core.config import settings
        monkeypatch.setattr(settings, "llm_extraction", True)

        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": "not valid json {"}}
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        from app.services.fact_extractor import extract_llm
        assert extract_llm("I love hiking.") == []

    def test_llm_parses_valid_response(self, monkeypatch):
        import httpx
        from unittest.mock import MagicMock
        from app.core.config import settings
        from app.services.fact_extractor import CandidateFact, extract_llm
        monkeypatch.setattr(settings, "llm_extraction", True)

        payload = {"facts": [{
            "key": "user_hobby",
            "value": "hiking",
            "value_type": "string",
            "confidence": 0.85,
            "source_type": "explicit_user_statement",
            "reason": "user stated hobby",
        }]}
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"message": {"content": json.dumps(payload)}}
        monkeypatch.setattr(httpx, "post", lambda *a, **kw: mock_resp)

        result = extract_llm("I love hiking.")
        assert len(result) == 1
        assert isinstance(result[0], CandidateFact)
        assert result[0].key == "user_hobby"
        assert result[0].value == "hiking"
        assert result[0].confidence == 0.85
