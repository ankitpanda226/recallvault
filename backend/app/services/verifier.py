"""Verification layer.

Per architecture section 8.5, a candidate fact must pass:
  - confidence threshold
  - policy check (explicit/durable vs transient/sensitive)
  - basic sanity (non-empty, reasonable length)

The verifier does NOT resolve conflicts — that is the conflict_resolver's
job. The verifier just decides: store this or drop it.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.fact_extractor import CandidateFact


@dataclass
class VerificationResult:
    accepted: bool
    reason: str


# Keys the architecture calls out as auto-storeable (durable)
_DURABLE_KEYS = {
    "user_name",
    "graduation_date",
    "preferred_roles",
    "response_style_preference",
    "architecture_decision",
    "bug_root_cause",
    "company_targets",
}

# Keys that require a higher bar (sensitive-ish)
_SENSITIVE_KEYS: set[str] = set()  # intentionally empty in MVP


def verify(fact: CandidateFact) -> VerificationResult:
    # confidence floor
    if fact.confidence < settings.min_extraction_confidence:
        return VerificationResult(False, f"confidence {fact.confidence:.2f} below threshold")

    # non-empty value
    if fact.value in (None, "", [], {}):
        return VerificationResult(False, "empty value")

    # unreasonably long string
    if isinstance(fact.value, str) and len(fact.value) > 500:
        return VerificationResult(False, "value too long")

    # sensitive keys require an explicit user statement
    if fact.key in _SENSITIVE_KEYS and fact.source_type != "explicit_user_statement":
        return VerificationResult(False, "sensitive key requires explicit statement")

    # policy: only auto-store known durable keys in MVP.
    # (Architecture allows "store conditionally" for medium-confidence inferred
    # facts — that path is open for extension.)
    if fact.key not in _DURABLE_KEYS:
        if fact.confidence < 0.9 or fact.source_type != "explicit_user_statement":
            return VerificationResult(False, f"key '{fact.key}' not in durable set and not high-confidence explicit")

    return VerificationResult(True, "passed verification")
