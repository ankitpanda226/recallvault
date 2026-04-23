"""Download longmemeval_s_cleaned.json from HuggingFace.

Usage (from repo root):
    python evaluation/longmemeval/download.py
    python evaluation/longmemeval/download.py --inspect   # dump first entry structure
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path

URL = (
    "https://huggingface.co/datasets/xiaowu0162/longmemeval-cleaned"
    "/resolve/main/longmemeval_s_cleaned.json"
)
DEFAULT_DEST = Path(__file__).resolve().parent / "data" / "longmemeval_s_cleaned.json"


def download(dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists():
        print(f"Already exists: {dest}  ({dest.stat().st_size / 1e6:.1f} MB)")
        return

    print(f"Downloading {URL}")
    print(f"  → {dest}")

    def _progress(count, block_size, total):
        if total <= 0:
            return
        pct = min(100, count * block_size * 100 // total)
        mb_done = count * block_size / 1e6
        mb_total = total / 1e6
        print(f"\r  {pct:3d}%  {mb_done:.1f}/{mb_total:.1f} MB", end="", flush=True)

    urllib.request.urlretrieve(URL, dest, reporthook=_progress)
    print(f"\nDone. {dest.stat().st_size / 1e6:.1f} MB")


def stats(dest: Path) -> list[dict]:
    print(f"\nLoading {dest.name} …")
    with open(dest) as f:
        data = json.load(f)

    # Dataset may be a list directly or wrapped in a dict
    if isinstance(data, dict):
        # Try common wrapper keys
        for key in ("data", "examples", "questions", "items"):
            if key in data:
                data = data[key]
                break
        else:
            # No known wrapper — treat top-level values as the list
            data = list(data.values())[0] if data else []

    n = len(data)
    if n == 0:
        print("WARNING: empty dataset")
        return data

    print(f"Questions:             {n}")

    # Count sessions per question using whatever field holds the haystack
    session_counts = []
    for entry in data:
        for field in ("haystack_sessions", "sessions", "haystack", "history"):
            if field in entry:
                session_counts.append(len(entry[field]))
                break

    if session_counts:
        avg = sum(session_counts) / len(session_counts)
        print(f"Avg sessions/question: {avg:.1f}")
        print(f"Min/Max sessions:      {min(session_counts)}/{max(session_counts)}")

    return data


def inspect_entry(data: list[dict]) -> None:
    if not data:
        return
    entry = data[0]
    print("\n--- First entry top-level keys ---")
    for k, v in entry.items():
        if isinstance(v, list):
            inner = v[0] if v else None
            inner_keys = list(inner.keys()) if isinstance(inner, dict) else type(inner).__name__
            print(f"  {k!r}: list[{len(v)}]  first elem keys: {inner_keys}")
        elif isinstance(v, dict):
            print(f"  {k!r}: dict  keys={list(v.keys())[:8]}")
        else:
            preview = str(v)[:80]
            print(f"  {k!r}: {type(v).__name__}  = {preview!r}")

    # Drill into first session / first turn if present
    for field in ("haystack_sessions", "sessions", "haystack", "history"):
        if field in entry and entry[field]:
            sess = entry[field][0]
            print(f"\n--- First session ({field}[0]) ---")
            if isinstance(sess, dict):
                for k, v in sess.items():
                    if isinstance(v, list):
                        inner = v[0] if v else None
                        inner_keys = list(inner.keys()) if isinstance(inner, dict) else type(inner).__name__
                        print(f"  {k!r}: list[{len(v)}]  first elem keys: {inner_keys}")
                    else:
                        print(f"  {k!r}: {type(v).__name__} = {str(v)[:60]!r}")
            break


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", default=str(DEFAULT_DEST))
    ap.add_argument("--inspect", action="store_true", help="Print first entry structure")
    args = ap.parse_args()

    dest = Path(args.dest)
    download(dest)
    data = stats(dest)
    if args.inspect:
        inspect_entry(data)


if __name__ == "__main__":
    main()
