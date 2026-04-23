"""Unit tests for verifier.verify().

Pure function tests — no DB, no network.
"""
from __future__ import annotations

import pytest

from app.services.fact_extractor import CandidateFact
from app.services.verifier import verify


def _fact(
    key="user_name",
    value="Alice",
    value_type="string",
    confidence=0.9,
    source_type="explicit_user_statement",
):
    return CandidateFact(
        key=key,
        value=value,
        value_type=value_type,
        confidence=confidence,
        source_type=source_type,
        reason="test",
    )


# ── Acceptance ────────────────────────────────────────────────────────────────

def test_accept_durable_key_above_floor():
    result = verify(_fact(key="user_name", confidence=0.9))
    assert result.accepted is True


def test_accept_all_durable_keys():
    durable = [
        "user_name", "graduation_date", "preferred_roles",
        "response_style_preference", "architecture_decision",
        "bug_root_cause", "company_targets",
    ]
    for key in durable:
        v = "test" if key != "preferred_roles" else ["backend"]
        vtype = "string" if key != "preferred_roles" else "list"
        result = verify(_fact(key=key, value=v, value_type=vtype, confidence=0.9))
        assert result.accepted is True, f"Expected {key} to be accepted"


def test_accept_unknown_key_high_confidence_explicit():
    """Unknown key is accepted if confidence >= 0.9 AND explicit statement."""
    result = verify(_fact(key="custom_key", confidence=0.9, source_type="explicit_user_statement"))
    assert result.accepted is True


# ── Rejection — confidence floor ──────────────────────────────────────────────

def test_reject_below_confidence_floor():
    """Confidence 0.55 is below the 0.6 floor — must reject."""
    result = verify(_fact(confidence=0.55))
    assert result.accepted is False


def test_reject_at_exact_floor_minus_epsilon():
    result = verify(_fact(confidence=0.599))
    assert result.accepted is False


def test_accept_at_exact_confidence_floor():
    """Confidence exactly at 0.6 should pass the floor check."""
    result = verify(_fact(key="user_name", confidence=0.6))
    assert result.accepted is True


# ── Rejection — empty value ───────────────────────────────────────────────────

def test_reject_empty_string_value():
    result = verify(_fact(value=""))
    assert result.accepted is False


def test_reject_empty_list_value():
    result = verify(_fact(key="preferred_roles", value=[], value_type="list"))
    assert result.accepted is False


def test_reject_none_value():
    result = verify(_fact(value=None))
    assert result.accepted is False


# ── Rejection — value too long ────────────────────────────────────────────────

def test_reject_string_value_over_500_chars():
    result = verify(_fact(value="x" * 501))
    assert result.accepted is False


def test_accept_string_value_exactly_500_chars():
    result = verify(_fact(value="x" * 500))
    assert result.accepted is True


# ── Rejection — non-durable key policy ───────────────────────────────────────

def test_reject_unknown_key_low_confidence():
    """Unknown key with confidence 0.85 (< 0.9) must be rejected."""
    result = verify(_fact(key="random_key", confidence=0.85, source_type="explicit_user_statement"))
    assert result.accepted is False


def test_reject_unknown_key_inferred_source():
    """Unknown key with high confidence but non-explicit source → rejected."""
    result = verify(_fact(key="random_key", confidence=0.95, source_type="inferred"))
    assert result.accepted is False


def test_reject_unknown_key_decision_source():
    result = verify(_fact(key="new_thing", confidence=0.95, source_type="decision"))
    assert result.accepted is False


# ── Reason strings ────────────────────────────────────────────────────────────

def test_rejection_reason_is_non_empty_string():
    result = verify(_fact(confidence=0.1))
    assert isinstance(result.reason, str)
    assert len(result.reason) > 0


def test_acceptance_reason_is_non_empty_string():
    result = verify(_fact())
    assert isinstance(result.reason, str)
    assert len(result.reason) > 0
