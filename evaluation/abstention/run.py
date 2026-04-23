"""RecallVault Abstention Benchmark.

Measures how reliably the response guard refuses to answer when no relevant
memory exists. Four categories stress different properties of the guard:

  empty_memory        — nothing ingested at all
  unrelated_memory    — stored content is on a completely different topic
  partial_memory      — related topic stored, but the specific answer absent
  adversarial_similarity — semantically close content, but lexical filter
                           should protect against false-positive cautious

Usage (from repo root):
    backend/.venv/bin/python evaluation/abstention/run.py
    backend/.venv/bin/python evaluation/abstention/run.py --limit 10
"""
from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import shutil
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ───────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

ABSTENTION_DIR = Path(__file__).resolve().parent
DEFAULT_CASES = ABSTENTION_DIR / "cases.jsonl"
DEFAULT_OUT_DIR = ABSTENTION_DIR / "results"

# ── Temp storage: set BEFORE any app module is imported ──────────────────────
_BENCH_STORAGE = tempfile.mkdtemp(prefix="rv_abs_")
os.environ["RV_STORAGE_ROOT"] = _BENCH_STORAGE


def _load_cases(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(f"Cases file not found: {path}")
    cases = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def _project_id(case_id: str) -> str:
    return "abs_" + hashlib.md5(case_id.encode()).hexdigest()[:12]


def _expected(case: dict) -> list[str]:
    """Return list of accepted modes for this case."""
    if "expected_mode_in" in case:
        return case["expected_mode_in"]
    return [case["expected_mode"]]


def run_case(case: dict) -> dict:
    """Ingest setup messages, query the guard, return result record."""
    from app.core.config import settings
    from app.db.models import Project
    from app.db.session import drop_project, project_session, registry_session
    from app.services import embedding_service, ingest_service, retrieval_service
    from app.services.response_guard import compose
    from app.utils.time import utcnow

    case_id: str = case["case_id"]
    category: str = case["category"]
    setup: list[str] = case["setup"]
    query: str = case["query"]
    accepted_modes = _expected(case)

    project_id = _project_id(case_id)

    # Create project
    with registry_session() as s:
        if s.query(Project).filter(Project.id == project_id).first() is None:
            s.add(Project(
                id=project_id, name=project_id, description="",
                created_at=utcnow(), config_json={},
            ))
    with project_session(project_id):
        pass  # initialize tables

    try:
        # Ingest setup messages
        for msg in setup:
            ingest_service.ingest(project_id, msg, speaker="user")

        # Retrieve and compose
        result = retrieval_service.retrieve(project_id, query, top_k=5)
        answer = compose(result)
        actual_mode = answer.mode
        hit = actual_mode in accepted_modes

        return {
            "case_id": case_id,
            "category": category,
            "expected": accepted_modes,
            "actual": actual_mode,
            "hit": hit,
        }

    finally:
        project_dir = settings.project_dir(project_id)
        drop_project(project_id)
        embedding_service._client_for.cache_clear()
        gc.collect()
        shutil.rmtree(project_dir, ignore_errors=True)


def _report(results: list[dict]) -> None:
    total = len(results)
    hits = sum(r["hit"] for r in results)

    by_cat: dict[str, list[dict]] = defaultdict(list)
    for r in results:
        by_cat[r["category"]].append(r)

    categories = [
        "empty_memory",
        "unrelated_memory",
        "partial_memory",
        "adversarial_similarity",
    ]

    # False-positive analysis: cases that were actual misses, by failure mode.
    # Only non-hits count; partial_memory cases that accept cautious are hits, not FPs.
    fp_cautious = [r for r in results if not r["hit"] and r["actual"] == "cautious"]
    fp_verified = [r for r in results if not r["hit"] and r["actual"] == "verified"]

    w = 30
    print()
    print("RecallVault Abstention Benchmark")
    print("=" * 50)
    pct = hits / total * 100 if total else 0
    print(f"{'Overall:':<{w}} {hits}/{total} = {pct:.1f}%")
    for cat in categories:
        rows = by_cat.get(cat, [])
        if not rows:
            continue
        n = len(rows)
        h = sum(r["hit"] for r in rows)
        p = h / n * 100
        print(f"  {(cat + ':'):<{w-2}} {h}/{n} = {p:.1f}%")

    print()
    print(f"False-positive cautious:  {len(fp_cautious)} cases  "
          f"(abstain expected but got cautious)")

    if fp_verified:
        print(f"False-positive verified:  {len(fp_verified)} cases  "
              f"(abstain expected but got verified — CRITICAL)")
        print()
        print("*** CRITICAL: guard claimed confidence without evidence ***")
        for r in fp_verified:
            print(f"  case_id={r['case_id']}  category={r['category']}")
    else:
        print(f"False-positive verified:  0 cases  (clean)")

    if fp_cautious:
        print()
        print("False-positive cautious detail:")
        for r in fp_cautious:
            print(f"  case_id={r['case_id']}  category={r['category']}")
    print()


def main() -> None:
    ap = argparse.ArgumentParser(description="RecallVault Abstention Benchmark")
    ap.add_argument("--limit", type=int, default=None,
                    help="Max number of cases to evaluate (default: all)")
    ap.add_argument("--cases", default=str(DEFAULT_CASES),
                    help="Path to cases.jsonl")
    ap.add_argument("--out", default=None,
                    help="Output JSONL path (default: results/run_<timestamp>.jsonl)")
    args = ap.parse_args()

    cases = _load_cases(Path(args.cases))
    if args.limit is not None:
        cases = cases[: args.limit]

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"run_{ts}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        from tqdm import tqdm
        iterator = tqdm(cases, desc="Abstention benchmark", unit="case")
    except ImportError:
        iterator = cases

    all_results: list[dict] = []

    with open(out_path, "w") as out_f:
        for case in iterator:
            row = run_case(case)
            out_f.write(json.dumps(row) + "\n")
            out_f.flush()
            all_results.append(row)

    print(f"\nResults written to: {out_path}")
    _report(all_results)

    # Exit non-zero if any false-positive verified — CI-friendly
    fp_verified = [
        r for r in all_results
        if "abstain" in r["expected"] and r["actual"] == "verified"
    ]
    if fp_verified:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    finally:
        shutil.rmtree(_BENCH_STORAGE, ignore_errors=True)
