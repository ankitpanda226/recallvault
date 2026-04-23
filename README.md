# RecallVault

**A verified, local-first persistent memory system for AI assistants — hybrid vector + structured storage with zero fake recall.**

RecallVault gives AI assistants a private, queryable long-term memory that runs entirely on your machine. It combines semantic vector search with a structured fact store and a three-tier response guard that explicitly refuses to answer when evidence is missing — eliminating hallucinated recall.

---

## Benchmark results

Within 0.4 pp of MemPalace's published **96.6% R@5** on [LongMemEval LME-S](https://github.com/xiaowu0162/longmemeval) (500 questions, 53-session haystack per question).

| Config | Embedder | Chunking | LongMemEval R@5 |
|---|---|---|---|
| Baseline | MiniLM-L6-v2 | Per-turn | 92.0% |
| + sliding window (Phase 2a) | MiniLM-L6-v2 | 3-turn, overlap=1 | 92.4% |
| + BGE-large (Phase 2b) | BGE-large-en-v1.5 | 3-turn, overlap=1 | **96.2%** |
| MemPalace (reference) | MiniLM-L6-v2 | Per-session | 96.6% |

Full methodology, per-category breakdown, and failure analysis: [evaluation/longmemeval/](evaluation/longmemeval/)

---

## How it works

RecallVault stores every memory in two parallel paths and decides at query time which to trust:

```
User message
     │
     ▼
 Ingest Service
  ├─ Chunk text → embed → ChromaDB (vector store)
  └─ Extract facts → SQLite (structured fact store)
                              │
                              ▼
                         Response Guard
                  ┌──────────┴──────────────┐
               verified                  cautious / abstain
          (fact store hit,           (semantic hit only,      (no relevant
           high confidence)           lexical overlap)         evidence)
               │                         │                        │
        Confident answer          Hedged answer            Explicit refusal
        with provenance           with disclaimer           (says "I don't know")
```

### Memory paths

| Path | Storage | When used |
|---|---|---|
| **Vector chunks** | ChromaDB (per-project collection) | Semantic similarity search — fuzzy, approximate |
| **Verified facts** | SQLite (per-project `facts.db`) | Structured key-value lookup — exact, versioned, with conflict resolution |

### Response guard modes

| Mode | Trigger | Behavior |
|---|---|---|
| `verified` | Fact hit with confidence ≥ 0.75 | Answers confidently with provenance chain |
| `cautious` | Semantic chunk hit + lexical overlap with query | Answers with explicit disclaimer |
| `abstain` | No topically-relevant evidence | Refuses to answer — no hallucination |

### Project isolation

Each project gets its own storage directory under `storage/data/<project_id>/`:
- `vector_store/` — ChromaDB collection
- `facts.db` — SQLite with versioned fact history
- `raw_archives/` — original ingested text

Projects never share data. The registry (`storage/registry.db`) tracks project metadata.

---

## Features

- **Zero fake recall** — the response guard always abstains rather than hallucinate
- **Versioned facts** — every fact update creates a new version; full history queryable via `/memory/history/{key}`
- **Conflict resolution** — configurable strategy (`newer_explicit_wins` by default) when facts contradict
- **Recency-weighted retrieval** — chunks scored by semantic similarity + exponential recency decay
- **Project isolation** — multiple independent memory spaces per deployment
- **Local-first** — all data stored on disk, no cloud dependencies
- **Streaming ingest** — results streamed to JSONL so partial runs are recoverable

---

## Setup

**Requirements:** Python 3.11+, Node 18+

```bash
# 1. Clone
git clone https://github.com/ankitpanda226/recallvault.git
cd recallvault

# 2. Backend
cd backend
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Frontend
cd ../frontend
npm install
```

### Dev dependencies (tests only)

```bash
cd backend
pip install -r requirements-dev.txt
```

`requirements-dev.txt` contains `pytest` and `pytest-cov`. It is separate from `requirements.txt` and not needed to run the application.

---

## Running

```bash
# Start the API server (from backend/)
cd backend
source .venv/bin/activate
uvicorn app.main:app --reload
# → http://localhost:8000
# → http://localhost:8000/docs  (Swagger UI)

# Start the frontend (from frontend/)
cd frontend
npm run dev
# → http://localhost:5173

# Run the demo script
backend/.venv/bin/python scripts/demo.py
```

---

## API overview

| Endpoint | Method | Description |
|---|---|---|
| `/projects` | GET / POST | List or create memory projects |
| `/memory/ingest` | POST | Ingest text into a project |
| `/memory/search` | GET | Semantic search (`?project_id=&q=`) |
| `/memory/facts/{key}` | GET | Retrieve current value of a structured fact |
| `/memory/history/{key}` | GET | Full version history of a fact |
| `/memory/update` | POST | Explicit fact update (goes through conflict resolver) |
| `/memory/forget` | POST | Soft-delete a fact |
| `/chat` | POST | Query memory with response guard — returns `verified`, `cautious`, or `abstain` |
| `/health` | GET | Health check |

Full interactive docs at `/docs` when the server is running.

---

## Configuration

All settings are read from environment variables prefixed `RV_`:

| Variable | Default | Description |
|---|---|---|
| `RV_STORAGE_ROOT` | `./storage` | Root directory for all project data |
| `RV_EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Sentence-transformers model name |
| `RV_TOP_K_SEMANTIC` | `5` | Number of chunks returned by semantic search |
| `RV_RECENCY_HALF_LIFE_DAYS` | `30` | Half-life for recency decay in scoring |
| `RV_VERIFIED_CONFIDENCE_MIN` | `0.75` | Minimum confidence to trust a fact as `verified` |
| `RV_CAUTIOUS_SEMANTIC_MIN` | `0.45` | Minimum similarity score to attempt a `cautious` answer |
| `RV_LLM_EXTRACTION` | `false` | Enable LLM-based fact extraction (off by default) |
| `RV_CONFLICT_STRATEGY` | `newer_explicit_wins` | How conflicting facts are resolved |

---

## Running the unit tests

```bash
cd backend
pip install -r requirements-dev.txt   # once
pytest tests/ -v
pytest tests/ --cov=app/services      # with coverage
```

92 tests covering `response_guard`, `conflict_resolver`, `ingest_service`,
`retrieval_service`, `fact_extractor`, and `verifier`. No network access or
model downloads required — embedding calls are mocked.

---

## Running the benchmark

```bash
# Download dataset (277 MB, one-time)
backend/.venv/bin/python evaluation/longmemeval/download.py

# Stratified 60-question diagnostic (~17 min)
backend/.venv/bin/python evaluation/longmemeval/run.py --stratified 10

# Full 500-question baseline run (~2.5 hours)
backend/.venv/bin/python evaluation/longmemeval/run.py

# Phase 2b — sliding window + BGE-large (~3-4 hours, model auto-downloaded)
backend/.venv/bin/python evaluation/longmemeval/run.py --window 3 --overlap 1 --embedder bge-large
```

Results are written to `evaluation/longmemeval/results/` as JSONL, streamed per question so partial runs are readable.

---

## Project structure

```
recallvault/
├── backend/
│   ├── app/
│   │   ├── api/          # FastAPI routers (memory, chat, projects, admin)
│   │   ├── core/         # Config (RV_* env vars), logging
│   │   ├── db/           # SQLAlchemy models, session management, registry
│   │   ├── schemas/      # Pydantic request/response schemas
│   │   ├── services/     # Core logic
│   │   │   ├── embedding_service.py   # ChromaDB + sentence-transformers
│   │   │   ├── ingest_service.py      # Chunk, embed, extract facts
│   │   │   ├── retrieval_service.py   # Semantic + fact search + rerank
│   │   │   ├── fact_extractor.py      # Fact extraction pipeline
│   │   │   ├── conflict_resolver.py   # Fact conflict resolution
│   │   │   ├── response_guard.py      # verified / cautious / abstain logic
│   │   │   ├── verifier.py            # Fact verification
│   │   │   └── event_logger.py        # Audit log
│   │   └── utils/        # Time helpers, chunking utilities
│   └── requirements.txt
├── frontend/             # React UI (Vite)
├── scripts/
│   └── demo.py           # End-to-end demo
├── evaluation/
│   ├── longmemeval/      # R@5 benchmark (download, adapter, runner, results)
│   └── benchmarks/       # Semantic recall unit tests
├── docs/
│   └── architecture.svg
└── storage/              # Runtime data (gitignored)
```

---

## Tech stack

| Layer | Technology |
|---|---|
| API | FastAPI + Uvicorn |
| Vector store | ChromaDB 0.5 |
| Embeddings | sentence-transformers (MiniLM-L6-v2 / BGE-large-en-v1.5) |
| Structured facts | SQLite via SQLAlchemy 2.0 |
| Schema validation | Pydantic v2 |
| Frontend | React + Vite |
| Benchmark | LongMemEval LME-S (500 questions) |

---

## License

MIT — see [LICENSE](LICENSE).
