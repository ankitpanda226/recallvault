"""Sentence-aware chunking.

For short messages (typical chat), each message is its own chunk.
For longer blocks of text (pasted documents, meeting notes), we split on
sentence boundaries with a small overlap window to preserve context.
"""
from __future__ import annotations

import re

_SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def split_sentences(text: str) -> list[str]:
    text = normalize(text)
    if not text:
        return []
    parts = _SENT_SPLIT.split(text)
    return [p.strip() for p in parts if p.strip()]


def chunk(text: str, max_chars: int = 600, overlap_sentences: int = 1) -> list[str]:
    """Return a list of chunks. Small inputs return a single-element list."""
    text = normalize(text)
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    sents = split_sentences(text)
    if not sents:
        return [text]

    chunks: list[str] = []
    buf: list[str] = []
    cur_len = 0
    for s in sents:
        if cur_len + len(s) + 1 > max_chars and buf:
            chunks.append(" ".join(buf))
            # overlap: keep last N sentences
            if overlap_sentences > 0:
                buf = buf[-overlap_sentences:]
                cur_len = sum(len(x) + 1 for x in buf)
            else:
                buf = []
                cur_len = 0
        buf.append(s)
        cur_len += len(s) + 1

    if buf:
        chunks.append(" ".join(buf))
    return chunks
