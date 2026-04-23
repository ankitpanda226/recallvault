"""LongMemEval R@5 benchmark runner for RecallVault.

Usage (from repo root):
    python evaluation/longmemeval/run.py --limit 25
    python evaluation/longmemeval/run.py --stratified 10              # 10/category = 60 total
    python evaluation/longmemeval/run.py --window 3 --overlap 1       # sliding-window chunks
    python evaluation/longmemeval/run.py --embedder bge-large         # swap embedding model
    python evaluation/longmemeval/run.py                              # full 500-question run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

LONGMEMEVAL_DIR = Path(__file__).resolve().parent
DEFAULT_DATA = LONGMEMEVAL_DIR / "data" / "longmemeval_s_cleaned.json"
DEFAULT_OUT_DIR = LONGMEMEVAL_DIR / "results"

# ── Storage root: set BEFORE any app module is imported ─────────────────────
# Use a temp dir so benchmark projects don't pollute the main storage tree.
# Adapter.py cleans up per-project dirs; the temp dir itself is removed at end.
_BENCH_STORAGE = tempfile.mkdtemp(prefix="rv_lme_")
os.environ["RV_STORAGE_ROOT"] = _BENCH_STORAGE


def _load_data(path: Path) -> list[dict]:
    if not path.exists():
        sys.exit(
            f"Dataset not found: {path}\n"
            "Run: python evaluation/longmemeval/download.py"
        )
    with open(path) as f:
        return json.load(f)


EMBEDDER_MODELS = {
    "minilm": "all-MiniLM-L6-v2",
    "bge-large": "BAAI/bge-large-en-v1.5",
}


def _report(results: list[dict], embedder: str = "minilm", window: int = 1, overlap: int = 0) -> None:
    total = len(results)
    hits = sum(r["hit"] for r in results)

    by_type: dict[str, list[bool]] = defaultdict(list)
    for r in results:
        by_type[r["question_type"]].append(r["hit"])

    categories = [
        "single-session-user",
        "single-session-assistant",
        "single-session-preference",
        "multi-session",
        "temporal-reasoning",
        "knowledge-update",
    ]

    model_name = EMBEDDER_MODELS.get(embedder, embedder)
    chunk_desc = f"window={window},overlap={overlap}" if window > 1 else "per-turn"
    header = f"LongMemEval R@5 — RecallVault ({model_name}, {chunk_desc})"
    w = 38
    print()
    print(header)
    print("=" * max(53, len(header)))
    pct = hits / total * 100 if total else 0
    print(f"{'Overall:':<{w}} {hits}/{total} = {pct:.1f}%")
    for cat in categories:
        cat_results = by_type.get(cat, [])
        if not cat_results:
            continue
        n = len(cat_results)
        h = sum(cat_results)
        p = h / n * 100
        print(f"  {cat + ':':<{w-2}} {h}/{n} = {p:.1f}%")
    print()


def _stratified_sample(data: list[dict], n_per_category: int) -> list[dict]:
    """Return the first N entries of each question_type, preserving dataset order."""
    counts: dict[str, int] = defaultdict(int)
    out: list[dict] = []
    for entry in data:
        qt = entry["question_type"]
        if counts[qt] < n_per_category:
            out.append(entry)
            counts[qt] += 1
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description="LongMemEval R@5 benchmark for RecallVault")
    ap.add_argument("--limit", type=int, default=None,
                    help="Max number of questions to evaluate (default: all 500)")
    ap.add_argument("--stratified", type=int, default=None, metavar="N",
                    help="Pick the first N questions per category (6 categories × N total)")
    ap.add_argument("--window", type=int, default=1, metavar="N",
                    help="Turns per sliding-window chunk (default: 1 = per-turn)")
    ap.add_argument("--overlap", type=int, default=0, metavar="K",
                    help="Turn overlap between consecutive windows (default: 0)")
    ap.add_argument("--embedder", default="minilm",
                    choices=list(EMBEDDER_MODELS),
                    help="Embedding model: minilm (default) or bge-large")
    ap.add_argument("--data", default=str(DEFAULT_DATA),
                    help="Path to longmemeval_s_cleaned.json")
    ap.add_argument("--out", default=None,
                    help="Output JSONL path (default: results/run_<timestamp>[_config].jsonl)")
    args = ap.parse_args()

    if args.limit is not None and args.stratified is not None:
        ap.error("--limit and --stratified are mutually exclusive")
    if args.overlap >= args.window:
        ap.error("--overlap must be less than --window")

    # Set embedding model env var BEFORE any app module is imported.
    # Settings() reads RV_EMBEDDING_MODEL on first instantiation inside run_question().
    os.environ["RV_EMBEDDING_MODEL"] = EMBEDDER_MODELS[args.embedder]

    data = _load_data(Path(args.data))
    if args.stratified is not None:
        data = _stratified_sample(data, args.stratified)
    elif args.limit is not None:
        data = data[: args.limit]

    # Build a config suffix for the output filename so runs are self-describing.
    suffix_parts = []
    if args.window > 1:
        suffix_parts.append(f"w{args.window}o{args.overlap}")
    if args.embedder != "minilm":
        suffix_parts.append(args.embedder.replace("-", ""))
    config_suffix = ("_" + "_".join(suffix_parts)) if suffix_parts else ""

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    out_path = Path(args.out) if args.out else DEFAULT_OUT_DIR / f"run_{ts}{config_suffix}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Import adapter after both env vars are set.
    from adapter import run_question  # noqa: E402

    try:
        from tqdm import tqdm
        iterator = tqdm(data, desc="LongMemEval R@5", unit="q")
    except ImportError:
        iterator = data

    all_results: list[dict] = []

    with open(out_path, "w") as out_f:
        for entry in iterator:
            qr = run_question(entry, window=args.window, overlap=args.overlap)
            row = {
                "question_id": qr.question_id,
                "question_type": qr.question_type,
                "gold_session_ids": qr.gold_session_ids,
                "retrieved_session_ids": qr.retrieved_session_ids,
                "hit": qr.hit,
            }
            out_f.write(json.dumps(row) + "\n")
            out_f.flush()
            all_results.append(row)

    print(f"\nResults written to: {out_path}")
    _report(all_results, embedder=args.embedder, window=args.window, overlap=args.overlap)


if __name__ == "__main__":
    import shutil
    try:
        main()
    finally:
        shutil.rmtree(_BENCH_STORAGE, ignore_errors=True)
