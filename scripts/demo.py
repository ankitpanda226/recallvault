"""End-to-end demo of RecallVault.

Exercises the full pipeline without needing the web server:
  - creates two isolated projects
  - ingests a stream of messages
  - demonstrates conflict resolution (superseding)
  - runs verified / cautious / abstain retrieval paths
  - verifies project isolation

Run from repo root:
    python scripts/demo.py
"""
from __future__ import annotations

import sys
from pathlib import Path
import os
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

# Make backend importable when running from repo root
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.db.models import Project  # noqa: E402
from app.db.session import project_session, registry_session  # noqa: E402
from app.services import ingest_service, response_guard, retrieval_service  # noqa: E402
from app.utils.time import utcnow  # noqa: E402


def banner(s: str) -> None:
    print("\n" + "=" * 72)
    print(s)
    print("=" * 72)


def ensure_project(project_id: str, name: str) -> None:
    with registry_session() as s:
        if s.query(Project).filter(Project.id == project_id).first() is None:
            s.add(Project(id=project_id, name=name, description="", created_at=utcnow(), config_json={}))
    # open once to create tables
    with project_session(project_id):
        pass


def show_ingest(report) -> None:
    print(f"  chunks: {len(report.chunk_ids)}  candidates: {report.candidates}  "
          f"accepted: {report.accepted}  rejected: {report.rejected}")
    for f in report.facts:
        print(f"    - [{f.action:>10}] {f.key} = {f.value}   ({f.reason})")


def ask(project_id: str, q: str) -> None:
    print(f"\n  Q: {q}")
    result = retrieval_service.retrieve(project_id, q)
    guarded = response_guard.compose(result)
    print(f"  mode: {guarded.mode}")
    print(f"  A: {guarded.answer}")
    if guarded.provenance:
        for p in guarded.provenance:
            print(f"     provenance: fact_id={p.fact_id} v{p.version} source={p.source_chunk_id}")


def main() -> None:
    banner("RecallVault end-to-end demo")

    # Two projects to demonstrate isolation
    ensure_project("coding_agent", "Coding Agent Memory")
    ensure_project("career_assistant", "Career Assistant Memory")

    banner("1. Ingesting user statements into 'coding_agent'")
    r = ingest_service.ingest("coding_agent",
        "Use Postgres for durable memory. The root cause is a stale cache in the worker pool.")
    show_ingest(r)

    r = ingest_service.ingest("coding_agent", "I prefer concise answers.")
    show_ingest(r)

    banner("2. Ingesting user statements into 'career_assistant'")
    r = ingest_service.ingest("career_assistant",
        "My name is Sam. My expected graduation is December 2026. I prefer backend engineer roles.")
    show_ingest(r)

    banner("3. Retrieval: verified path")
    ask("career_assistant", "What kind of roles am I targeting?")
    ask("career_assistant", "When do I finish school?")

    banner("4. Conflict resolution: updating graduation date")
    r = ingest_service.ingest("career_assistant", "Actually my graduation is May 2027.")
    show_ingest(r)
    ask("career_assistant", "When do I graduate?")

    banner("5. History of the 'graduation_date' fact")
    from app.db.models import MemoryFact
    with project_session("career_assistant") as s:
        rows = (
            s.query(MemoryFact)
            .filter(MemoryFact.key == "graduation_date")
            .order_by(MemoryFact.version.asc())
            .all()
        )
        for r in rows:
            print(f"   v{r.version}  status={r.status}  value={r.value_json}  "
                  f"source={r.source_chunk_id}  updated={r.updated_at.isoformat()}")

    banner("6. Abstain path (no evidence)")
    ask("career_assistant", "What is my favorite color?")

    banner("7. Cautious path (fuzzy semantic match only)")
    # The "stale cache" note isn't a verified fact under a question-ish key,
    # but semantic search should still surface it.
    ask("coding_agent", "Tell me about cache problems.")

    banner("8. Project isolation check")
    ask("coding_agent", "When do I graduate?")
    print("  (should abstain — the graduation fact lives only in 'career_assistant')")

    banner("done")


if __name__ == "__main__":
    main()
