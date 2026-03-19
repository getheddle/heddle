"""loom.contrib.rag — RAG pipeline for social media stream analysis.

Processes multi-channel social media streams (Telegram, etc.) through
an LLM-backed analysis pipeline:

    Ingest → Mux → Chunk → Embed/Analyze

Requires the ``rag`` optional dependency::

    pip install loom[rag]

Stages:
    ingestion   — Platform-specific adapters (Telegram JSON exports)
    mux         — Merge and window multi-channel streams chronologically
    chunker     — Split posts into text chunks for embedding
    analysis    — LLM actors: trends, corroboration, anomalies, extraction
    vectorstore — DuckDB-backed embedding storage and similarity search
    tools       — RTL text normalization, temporal batching utilities
    backends    — Loom SyncProcessingBackend wrappers for pipeline stages
"""

__all__ = [
    "analysis",
    "backends",
    "chunker",
    "ingestion",
    "mux",
    "schemas",
    "tools",
    "vectorstore",
]
