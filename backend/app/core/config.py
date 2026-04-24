"""Configuration for RecallVault.

Local-first: data lives under STORAGE_ROOT/data/{project_id}/. Uses plain
os.environ reads (prefixed RV_) to keep the dependency surface minimal.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(f"RV_{name}", default)


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    v = _env(name, "1" if default else "0").strip().lower()
    return v in ("1", "true", "yes", "on")


_DEFAULT_STORAGE = Path(__file__).resolve().parents[3] / "storage"


@dataclass
class Settings:
    storage_root: Path = field(
        default_factory=lambda: Path(_env("STORAGE_ROOT", str(_DEFAULT_STORAGE)))
    )

    # Embedding
    embedding_model: str = field(
        default_factory=lambda: _env("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
    )

    # Retrieval
    top_k_semantic: int = field(default_factory=lambda: _env_int("TOP_K_SEMANTIC", 5))
    recency_half_life_days: float = field(
        default_factory=lambda: _env_float("RECENCY_HALF_LIFE_DAYS", 30.0)
    )

    # Guard thresholds
    verified_confidence_min: float = field(
        default_factory=lambda: _env_float("VERIFIED_CONFIDENCE_MIN", 0.75)
    )
    cautious_semantic_min: float = field(
        default_factory=lambda: _env_float("CAUTIOUS_SEMANTIC_MIN", 0.45)
    )

    # Extraction
    llm_extraction: bool = field(default_factory=lambda: _env_bool("LLM_EXTRACTION", False))
    min_extraction_confidence: float = field(
        default_factory=lambda: _env_float("MIN_EXTRACTION_CONFIDENCE", 0.6)
    )

    # Conflict handling
    conflict_strategy: str = field(
        default_factory=lambda: _env("CONFLICT_STRATEGY", "newer_explicit_wins")
    )

    # Chunking mode
    chunk_mode: str = field(
        default_factory=lambda: _env("CHUNK_MODE", "per_turn")
    )  # "per_turn" | "per_session" | "sliding_window"
    chunk_window_size: int = field(
        default_factory=lambda: _env_int("CHUNK_WINDOW_SIZE", 3)
    )
    chunk_overlap: int = field(
        default_factory=lambda: _env_int("CHUNK_OVERLAP", 1)
    )

    # LLM fact extraction (Ollama)
    llm_model: str = field(
        default_factory=lambda: _env("LLM_MODEL", "llama3.1:8b")
    )
    llm_base_url: str = field(
        default_factory=lambda: _env("LLM_BASE_URL", "http://localhost:11434")
    )
    llm_timeout: float = field(
        default_factory=lambda: _env_float("LLM_TIMEOUT", 30.0)
    )

    @property
    def data_root(self) -> Path:
        return self.storage_root / "data"

    @property
    def registry_db_path(self) -> Path:
        return self.storage_root / "registry.db"

    def project_dir(self, project_id: str) -> Path:
        return self.data_root / project_id

    def project_facts_db(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "facts.db"

    def project_vector_dir(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "vector_store"

    def project_raw_archive(self, project_id: str) -> Path:
        return self.project_dir(project_id) / "raw_archives"


settings = Settings()
