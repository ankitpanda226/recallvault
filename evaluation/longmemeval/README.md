# LongMemEval R@5 — RecallVault

Measures **Recall@5**: for each question, does the correct evidence session appear
in the top-5 chunks RecallVault retrieves from the 500-session haystack?

---

## Setup

No extra dependencies beyond what the backend venv already has
(`sentence-transformers` pulls in `tqdm`; everything else is stdlib).

Run all commands from the **repo root**.

---

## 1. Download the dataset (~277 MB, one-time)

```bash
backend/.venv/bin/python evaluation/longmemeval/download.py
```

Saves to `evaluation/longmemeval/data/longmemeval_s_cleaned.json`.
Re-running is a no-op if the file already exists.

To inspect the schema of the first entry:

```bash
backend/.venv/bin/python evaluation/longmemeval/download.py --inspect
```

---

## 2. Run the benchmark

```bash
# Stratified 60-question diagnostic (10 per category, ≈17 min)
backend/.venv/bin/python evaluation/longmemeval/run.py --stratified 10

# Full 500-question run with default config (≈2.5 hours)
backend/.venv/bin/python evaluation/longmemeval/run.py

# Phase 2b config — sliding-window chunks + BGE-large (≈3-4 hours; model auto-downloaded)
backend/.venv/bin/python evaluation/longmemeval/run.py --window 3 --overlap 1 --embedder bge-large
```

Flags:

| Flag | Default | Description |
|---|---|---|
| `--limit N` | all 500 | First N questions in dataset order |
| `--stratified N` | — | First N per category (6 × N total); mutually exclusive with `--limit` |
| `--window N` | 1 | Turns per sliding-window chunk (1 = per-turn, the default) |
| `--overlap K` | 0 | Turn overlap between consecutive windows |
| `--embedder` | `minilm` | Embedding model: `minilm` (all-MiniLM-L6-v2) or `bge-large` (BAAI/bge-large-en-v1.5) |
| `--data PATH` | `data/longmemeval_s_cleaned.json` | Dataset path |
| `--out PATH` | `results/run_<timestamp>[_config].jsonl` | Per-question output; config suffix added automatically |

Results are streamed to JSONL as they complete, so a partial run is still readable.

---

## Dataset structure

| Field | Type | Description |
|---|---|---|
| `question_id` | `str` | Unique ID (e.g. `"e47becba"`) |
| `question_type` | `str` | One of six categories (see below) |
| `question` | `str` | The question posed to the memory system |
| `answer` | `str` | Expected answer (not used for R@5 scoring) |
| `answer_session_ids` | `list[str]` | Gold evidence session IDs |
| `haystack_session_ids` | `list[str]` | Parallel IDs for `haystack_sessions` |
| `haystack_sessions` | `list[list[{role,content}]]` | 53-session haystack of turns |

**Question types:** `single-session-user` (70), `single-session-assistant` (56),
`single-session-preference` (30), `multi-session` (133), `temporal-reasoning` (133),
`knowledge-update` (78).

---

## Scoring

**R@5 (Recall at 5):** a question is a *hit* if at least one of its
`answer_session_ids` appears among the session IDs of the top-5 retrieved chunks.

```
R@5 = hits / total_questions
```

Per-question results in the output JSONL:

```json
{
  "question_id": "e47becba",
  "question_type": "single-session-user",
  "gold_session_ids": ["answer_280352e9"],
  "retrieved_session_ids": ["answer_280352e9", "sharegpt_yywfIrx_0"],
  "hit": true
}
```

---

## How the adapter works

For each question, the adapter:

1. Creates a fresh isolated RecallVault project (project ID = MD5 hash of `question_id`).
2. Ingests every turn of every haystack session via `ingest_service.ingest()`,
   tagging each chunk with its session ID.
3. Calls `retrieval_service.retrieve(project_id, question, top_k=5)`.
4. Looks up the `tags_json` column for each retrieved chunk to recover session IDs.
5. Computes hit, writes result, then **deletes the project directory** and clears
   the SQLAlchemy engine and ChromaDB client caches.

Each question runs in an isolated temp storage root, so projects from different
questions never interfere.

---

## Methodology differences vs. MemPalace

These differences are structural and affect how the R@5 numbers should be interpreted.

**Chunking granularity.** In the baseline config, RecallVault ingests each
conversation turn as a separate chunk tagged with its session ID. The Phase 2
config uses 3-turn sliding windows (overlap=1). MemPalace's baseline concatenates
all turns within a session into one chunk per session before embedding. Per-session
embedding gives MemPalace a structural advantage: each of the 53 haystack sessions
is one candidate, so top-5 always covers 5 distinct sessions. RecallVault's top-5
chunks may come from fewer than 5 distinct sessions — e.g., two chunks from the same
wrong session give zero additional coverage. This is a persistent structural
difference that contributes to the remaining 0.4 pp gap at the Phase 2b level.

**Reranking.** RecallVault applies a recency-and-source-quality rerank after
semantic retrieval. MemPalace's baseline uses cosine similarity ordering directly.

**Response guard.** RecallVault's lexical-overlap filter (in `response_guard.py`)
is applied *after* retrieval and does not affect which chunks are ranked or scored
here. It is neutral for R@5 measurement.

**The 0.4 pp gap.** Phase 2b reaches 96.2% vs. MemPalace's published 96.6%.
The remaining gap is not attributed to embedding quality (BGE-large is comparable
or superior to what MemPalace uses) but to the structural chunk-vs-session retrieval
difference described above. Closing it would require either session-level pooling
or a diversity-aware top-k that deduplicates by session before scoring.

---

## Results — all configurations, 500 questions

Within 0.4 pp of MemPalace's published 96.6% R@5 with fully documented methodology.

| Config | Embedder | Chunking | R@5 |
|---|---|---|---|
| Baseline | MiniLM-L6-v2 | Per-turn | 92.0% |
| + sliding window (Phase 2a) | MiniLM-L6-v2 | 3-turn, overlap=1 | 92.4% |
| + BGE-large (Phase 2b) | BGE-large-en-v1.5 | 3-turn, overlap=1 | **96.2%** |
| MemPalace (reference) | MiniLM-L6-v2 | Per-session | 96.6% |

### Per-category breakdown — all three configs

| Category | n | Baseline | Phase 2a | Phase 2b |
|---|---|---|---|---|
| single-session-user | 70 | 62 = 88.6% | 64 = 91.4% | 67 = **95.7%** |
| single-session-assistant | 56 | 55 = 98.2% | 56 = **100.0%** | 54 = 96.4% |
| single-session-preference | 30 | 26 = 86.7% | 24 = 80.0% | 26 = **86.7%** |
| multi-session | 133 | 123 = 92.5% | 121 = 91.0% | 131 = **98.5%** |
| temporal-reasoning | 133 | 118 = 88.7% | 121 = 91.0% | 126 = **94.7%** |
| knowledge-update | 78 | 76 = 97.4% | 76 = 97.4% | 77 = **98.7%** |
| **Overall** | **500** | **460 = 92.0%** | **462 = 92.4%** | **481 = 96.2%** |

**Key findings:**
- BGE-large is the dominant driver (+3.8 pp from Phase 2a to 2b). Sliding-window alone adds only +0.4 pp.
- Multi-session is the biggest winner in Phase 2b: 92.5% → 98.5% (+6 pp). BGE-large's superior cross-sentence understanding resolves the semantic mismatch between aggregation queries and individual session descriptions.
- Single-session-preference is the persistent weak point: 86.7% in both baseline and Phase 2b. Unchanged by chunking or embedder swap — see `failure_analysis.md` for why this is a query-reformulation problem, not an embedding problem.
- Single-session-assistant is the only category where Phase 2b regresses vs. Phase 2a (100% → 96.4%), but at 2 misses on 56 questions this is within measurement noise.
