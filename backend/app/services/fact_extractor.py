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

import json
import re
from dataclasses import dataclass, asdict
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


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

_LLM_SYSTEM_PROMPT = """\
You extract personal facts from user messages.
Return a JSON object with a "facts" key containing a list of facts.
Each fact must have exactly these fields:
  key        — snake_case identifier (e.g. user_name, preferred_language, graduation_date)
  value      — extracted value (string, number, list, or boolean)
  value_type — one of: string, list, number, bool
  confidence — float 0.0–1.0
  source_type — one of: explicit_user_statement, inferred, decision
  reason     — one-sentence explanation

Only extract clear, factual personal information, preferences, or decisions.
If no facts are present, return {"facts": []}.
Do not invent facts not supported by the text."""


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
    """LLM-based extraction via Ollama. Returns [] on any failure."""
    payload = {
        "model": settings.llm_model,
        "format": "json",
        "stream": False,
        "messages": [
            {"role": "system", "content": _LLM_SYSTEM_PROMPT},
            {"role": "user", "content": text},
        ],
    }

    try:
        response = httpx.post(
            f"{settings.llm_base_url}/api/chat",
            json=payload,
            timeout=settings.llm_timeout,
        )
        content = response.json()["message"]["content"]
        parsed = json.loads(content)
    except httpx.ConnectError as e:
        log.warning("Ollama not reachable (is it running?): %s", e)
        return []
    except httpx.TimeoutException as e:
        log.warning("Ollama request timed out after %.0fs: %s", settings.llm_timeout, e)
        return []
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        log.warning("LLM extraction parse error: %s", e)
        return []

    if isinstance(parsed, dict):
        facts_raw = parsed.get("facts", [])
        if not isinstance(facts_raw, list):
            facts_raw = [facts_raw]
    elif isinstance(parsed, list):
        facts_raw = parsed
    else:
        return []

    out: list[CandidateFact] = []
    for item in facts_raw:
        if not isinstance(item, dict):
            continue
        key = item.get("key", "")
        value = item.get("value")
        if not key or value is None:
            continue
        vtype = item.get("value_type", "string")
        if vtype not in ("string", "list", "number", "bool"):
            vtype = "string"
        confidence = float(item.get("confidence", 0.7))
        confidence = max(0.0, min(1.0, confidence))
        source_type = item.get("source_type", "inferred")
        if source_type not in ("explicit_user_statement", "inferred", "decision"):
            source_type = "inferred"
        reason = item.get("reason", f"LLM extracted '{key}'")
        out.append(CandidateFact(
            key=key,
            value=value,
            value_type=vtype,
            confidence=confidence,
            source_type=source_type,
            reason=reason,
        ))
    return out


def extract(text: str) -> list[CandidateFact]:
    """Main extractor entry point. Dedupes by (key, str(value)).

    Rules run first. LLM runs only when rules return no candidates
    AND settings.llm_extraction is enabled (fallback, not parallel).
    """
    candidates = extract_rules(text)
    if not candidates and settings.llm_extraction:
        candidates = extract_llm(text)

    seen: set[tuple[str, str]] = set()
    deduped: list[CandidateFact] = []
    for c in candidates:
        sig = (c.key, str(c.value))
        if sig in seen:
            continue
        seen.add(sig)
        deduped.append(c)
    return deduped
