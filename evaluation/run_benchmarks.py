"""Run all benchmarks and print a summary report.

Usage (from repo root):
    python evaluation/run_benchmarks.py

Each benchmark file exercises a specific property of the system:
  exact_recall       — verified retrieval of stored facts
  conflict           — newer-wins supersession correctness
  hallucination      — abstention when no evidence exists
  semantic_recall    — fuzzy retrieval via vector search
  isolation          — no cross-project leakage

The runner uses a fresh temporary storage root for each scenario to avoid
cross-test contamination.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

BENCH_DIR = Path(__file__).resolve().parent / "benchmarks"


def fresh_storage() -> str:
    d = tempfile.mkdtemp(prefix="rv_bench_")
    os.environ["RV_STORAGE_ROOT"] = d
    # Force config to reload with new env var. Clear any cached engines.
    for mod in list(sys.modules):
        if mod.startswith("app."):
            del sys.modules[mod]
    return d


def run_scenario(setup: list[str], query: str, project_id: str = "bench"):
    from app.services import ingest_service, retrieval_service, response_guard
    from app.db.models import Project
    from app.db.session import registry_session, project_session
    from app.utils.time import utcnow

    with registry_session() as s:
        if s.query(Project).filter(Project.id == project_id).first() is None:
            s.add(Project(id=project_id, name=project_id, description="", created_at=utcnow(), config_json={}))
    with project_session(project_id):
        pass

    for text in setup:
        ingest_service.ingest(project_id, text)

    result = retrieval_service.retrieve(project_id, query)
    return response_guard.compose(result)


def run_iso_scenario(setup_a: list[str], setup_b: list[str], query_in_b: str):
    from app.services import ingest_service, retrieval_service, response_guard
    from app.db.models import Project
    from app.db.session import registry_session, project_session
    from app.utils.time import utcnow

    for pid in ("proj_a", "proj_b"):
        with registry_session() as s:
            if s.query(Project).filter(Project.id == pid).first() is None:
                s.add(Project(id=pid, name=pid, description="", created_at=utcnow(), config_json={}))
        with project_session(pid):
            pass

    for text in setup_a:
        ingest_service.ingest("proj_a", text)
    for text in setup_b:
        ingest_service.ingest("proj_b", text)

    result = retrieval_service.retrieve("proj_b", query_in_b)
    return response_guard.compose(result)


def check_case(case: dict, guarded) -> tuple[bool, str]:
    if "expect_mode" in case:
        if guarded.mode != case["expect_mode"]:
            return False, f"mode={guarded.mode} expected {case['expect_mode']}"
    if "expect_mode_in" in case:
        if guarded.mode not in case["expect_mode_in"]:
            return False, f"mode={guarded.mode} expected one of {case['expect_mode_in']}"
    if "expect_mode_in_b" in case:
        if guarded.mode != case["expect_mode_in_b"]:
            return False, f"mode_in_b={guarded.mode} expected {case['expect_mode_in_b']}"
    if "expect_value_contains" in case:
        if case["expect_value_contains"].lower() not in guarded.answer.lower():
            return False, f"answer missing '{case['expect_value_contains']}': {guarded.answer!r}"
    return True, "ok"


def run_file(name: str, cases: list[dict], isolation: bool = False) -> tuple[int, int]:
    passed = 0
    failed = 0
    print(f"\n== {name} ==")
    for i, case in enumerate(cases, 1):
        tmp = fresh_storage()
        try:
            if isolation:
                guarded = run_iso_scenario(
                    case.get("project_a_setup", []),
                    case.get("project_b_setup", []),
                    case["query_in_b"],
                )
            else:
                guarded = run_scenario(case.get("setup", []), case["query"])
            ok, msg = check_case(case, guarded)
            if ok:
                passed += 1
                print(f"  [{i:>2}] PASS  {case.get('query') or case.get('query_in_b')}")
            else:
                failed += 1
                print(f"  [{i:>2}] FAIL  {case.get('query') or case.get('query_in_b')}  ({msg})")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return passed, failed


def load(name: str) -> list[dict]:
    path = BENCH_DIR / f"{name}.jsonl"
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def main() -> None:
    totals = [0, 0]
    for name in ("exact_recall", "conflict", "hallucination", "semantic_recall"):
        p, f = run_file(name, load(name))
        totals[0] += p
        totals[1] += f

    p, f = run_file("isolation", load("isolation"), isolation=True)
    totals[0] += p
    totals[1] += f

    print("\n" + "=" * 48)
    print(f"TOTAL: {totals[0]} passed, {totals[1]} failed")
    print("=" * 48)
    sys.exit(0 if totals[1] == 0 else 1)


if __name__ == "__main__":
    main()
