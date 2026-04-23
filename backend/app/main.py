"""RecallVault FastAPI entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import admin, chat, memory, projects
from app.core.logging import setup_logging

setup_logging()

app = FastAPI(
    title="RecallVault",
    version="0.1.0",
    description=(
        "A verified, local-first persistent memory system for AI assistants "
        "with project isolation, versioned memory, and zero fake recall."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(chat.router)
app.include_router(memory.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "recallvault"}
