"""Fact extraction.

Per the architecture (section 8.4), extraction uses rules + optional LLM.
The rule path ships by default so the demo works without any API key.
Enable the LLM path with RV_LLM_EXTRACTION=1.

Output format (what the verifier consumes):
  CandidateFact(
    key=str,              # stable snake_case identifier
    value=Any,            # string, list, number, bool
    value_type=str,       # "string" | "list" | "number" | "bool"
    confidence=float,     # [0, 1]
    source_type=str,      # "explicit_user_statement" | "inferred" | "decision"
    reason=str,           # human-readable rationale
  )
"""
from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from typing import Any

from app.core.config import settings


@dataclass
class CandidateFact:
    key: str
    value: Any
    value_type: str
    confidence: float
    source_type: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---- Rule patterns ----
#
# Each pattern maps a linguistic form to a (key, value_type, source_type,
# confidence) tuple. The architecture calls for explicit-preference and
# decision detection as the highest-priority forms; those are here.

_PATTERNS: list[tuple[re.Pattern[str], str, str, str, float]] = [
    # "my name is X"
    (re.compile(r"\bmy name is\s+([A-Za-z][\w\-' ]{1,60}?)\s*[\.\!]?$", re.I),
     "user_name", "string", "explicit_user_statement", 0.95),

    # "I prefer X roles" / "I prefer backend engineer roles"
    (re.compile(r"\bI prefer\s+([\w\- ]{2,80}?)\s+roles?\b", re.I),
     "preferred_roles", "list", "explicit_user_statement", 0.92),

    # "I prefer concise/terse/detailed answers/responses"
    (re.compile(r"\bI prefer\s+(concise|terse|detailed|brief|thorough|verbose)\s+(?:answers?|responses?|replies)\b", re.I),
     "response_style_preference", "string", "explicit_user_statement", 0.92),

    # "my expected graduation is X" / "my graduation date is X"
    (re.compile(r"\b(?:my )?(?:expected )?graduation(?:\s+date)?\s+is\s+([A-Za-z]+\s+\d{4}|\d{4}-\d{2}(?:-\d{2})?)", re.I),
     "graduation_date", "string", "explicit_user_statement", 0.95),

    # "I graduate in X" / "I graduate in December 2026"
    (re.compile(r"\bI graduate\s+in\s+([A-Za-z]+\s+\d{4}|\d{4})", re.I),
     "graduation_date", "string", "explicit_user_statement", 0.93),

    # Architecture / tooling decisions: "we chose X for Y" / "we decided on X"
    (re.compile(r"\b(?:we|I)\s+(?:chose|picked|selected|decided on)\s+([A-Za-z][\w\+\.\-]{1,40})\b", re.I),
     "architecture_decision", "string", "decision", 0.88),

    # "use Postgres for durable memory" — decision phrased as imperative
    (re.compile(r"\buse\s+([A-Z][\w\+\.\-]{1,40})\s+for\s+([\w\- ]{2,60})", re.I),
     "architecture_decision", "string", "decision", 0.82),

    # "the root cause is X"
    (re.compile(r"\bthe\s+root\s+cause\s+(?:is|was)\s+(.{3,120}?)[\.\!]?$", re.I),
     "bug_root_cause", "string", "explicit_user_statement", 0.85),

    # "I'm targeting X" / "I am targeting X companies"
    (re.compile(r"\bI(?:'m| am)\s+targeting\s+([\w\- ,]{2,100}?)(?:\s+companies|\s+roles|\s+jobs)?[\.\!]?$", re.I),
     "company_targets", "list", "explicit_user_statement", 0.85),
]


def _split_list(val: str) -> list[str]:
    parts = re.split(r"\s*(?:,|/|&| and )\s*", val.strip())
    return [p for p in parts if p]


def extract_rules(text: str) -> list[CandidateFact]:
    out: list[CandidateFact] = []
    for pat, key, vtype, stype, conf in _PATTERNS:
        for m in pat.finditer(text):
            raw = m.group(1).strip().rstrip(".!?")
            if vtype == "list":
                value: Any = _split_list(raw)
                if not value:
                    continue
            else:
                value = raw
            out.append(
                CandidateFact(
                    key=key,
                    value=value,
                    value_type=vtype,
                    confidence=conf,
                    source_type=stype,
                    reason=f"matched pattern for '{key}'",
                )
            )
    return out


def extract_llm(text: str) -> list[CandidateFact]:
    """LLM-based extraction. Placeholder that returns [] unless implemented.

    To implement: call an LLM with a strict JSON schema prompt that asks
    for a list of {key, value, value_type, confidence, source_type, reason}
    objects, then map to CandidateFact. Kept out of the default path so the
    demo runs with no API key.
    """
    return []


def extract(text: str) -> list[CandidateFact]:
    """Main extractor entry point. Dedupes by (key, str(value))."""
    candidates = extract_rules(text)
    if settings.llm_extraction:
        candidates.extend(extract_llm(text))

    seen: set[tuple[str, str]] = set()
    deduped: list[CandidateFact] = []
    for c in candidates:
        sig = (c.key, str(c.value))
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(c)
    return deduped
