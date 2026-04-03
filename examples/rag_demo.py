#!/usr/bin/env python3
"""
RAG Pipeline Demo — Telegram Channel Analysis
================================================
Demonstrates the heddle.contrib.rag module end-to-end:

  1. Ingest 4 Telegram channel exports
  2. Normalize Persian/RTL text
  3. Multiplex streams into chronological order with time windows
  4. Chunk posts into sentence-level segments
  5. Store chunks in DuckDB vector store (with optional embeddings)
  6. Print summary statistics

Usage:
    python examples/rag_demo.py [--embed]

    --embed   Generate embeddings via Ollama (requires running Ollama server)
              Without this flag, chunks are stored without embeddings.

Requires:
    pip install heddle-ai[rag]
"""
from __future__ import annotations

import sys
import time
from datetime import timedelta
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TELEGRAM_EXPORTS = [
    Path("/Volumes/SanDiskSSD/Downloads/Telegram Desktop/ChatExport_2026-03-12/result-1.json"),
    Path("/Volumes/SanDiskSSD/Downloads/Telegram Desktop/ChatExport_2026-03-12 (1)/result-2.json"),
    Path("/Volumes/SanDiskSSD/Downloads/Telegram Desktop/ChatExport_2026-03-12 (2)/result-3.json"),
    Path("/Volumes/SanDiskSSD/Downloads/Telegram Desktop/ChatExport_2026-03-12 (3)/result-4.json"),
]

DB_PATH = "/tmp/rag-demo.duckdb"
WINDOW_HOURS = 6
CHUNK_TARGET = 400
CHUNK_MAX = 600


def main() -> None:
    do_embed = "--embed" in sys.argv

    print("=" * 70)
    print("  heddle.contrib.rag — Telegram Channel Analysis Demo")
    print("=" * 70)

    # ------------------------------------------------------------------
    # Step 1: Ingest Telegram exports
    # ------------------------------------------------------------------
    print("\n[1/5] Ingesting Telegram exports...")
    from heddle.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor, DEFAULT_PROFILES

    ingestors = []
    for path in TELEGRAM_EXPORTS:
        if not path.exists():
            print(f"  SKIP (not found): {path.name}")
            continue
        t0 = time.perf_counter()
        ingestor = TelegramIngestor(path, min_text_len=10).load()
        posts = ingestor.ingest_all()
        elapsed = time.perf_counter() - t0

        profile = DEFAULT_PROFILES.get(ingestor.channel_id)
        bias_label = f" [{profile.bias.value}]" if profile else ""
        print(f"  {ingestor.channel_name:<30} id={ingestor.channel_id:>12}  "
              f"posts={len(posts):>5}{bias_label}  ({elapsed:.2f}s)")
        ingestors.append(ingestor)

    if not ingestors:
        print("No exports found. Check TELEGRAM_EXPORTS paths.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # Step 2: Normalize text (RTL / Persian)
    # ------------------------------------------------------------------
    print("\n[2/5] Normalizing text (RTL / Persian)...")
    from heddle.contrib.rag.tools.rtl_normalizer import normalize

    sample_count = 0
    for ingestor in ingestors:
        for post in ingestor.ingest_all()[:3]:
            result = normalize(post.text_clean)
            sample_count += 1
    print(f"  Normalized {sample_count} sample posts (showing first 3 per channel)")
    print(f"  RTL normalizer handles: ZWNJ, Arabic→Persian chars, digit normalization")

    # ------------------------------------------------------------------
    # Step 3: Multiplex streams
    # ------------------------------------------------------------------
    print("\n[3/5] Multiplexing streams into chronological order...")
    from heddle.contrib.rag.mux.stream_mux import merge_from_ingestors
    from heddle.contrib.rag.schemas.mux import MuxWindowConfig

    t0 = time.perf_counter()
    window_config = MuxWindowConfig(window_duration=timedelta(hours=WINDOW_HOURS))
    stream = merge_from_ingestors(ingestors, window_config=window_config)
    elapsed = time.perf_counter() - t0

    print(f"  Total entries:   {stream.total_entries}")
    print(f"  Channels:        {stream.channel_count}")
    print(f"  Time span:       {stream.time_span_hours:.1f} hours")
    print(f"  Windows ({WINDOW_HOURS}h):   {len(stream.window_ids)}")
    print(f"  Merge time:      {elapsed:.3f}s")

    # Show window distribution
    windows = stream.windows()
    print("\n  Window distribution:")
    for wid in sorted(windows.keys())[:10]:
        entries = windows[wid]
        channels = len({e.channel_id for e in entries})
        print(f"    {wid}: {len(entries):>4} entries, {channels} channels")
    if len(windows) > 10:
        print(f"    ... ({len(windows) - 10} more windows)")

    # ------------------------------------------------------------------
    # Step 4: Chunk posts
    # ------------------------------------------------------------------
    print(f"\n[4/5] Chunking posts (target={CHUNK_TARGET}, max={CHUNK_MAX})...")
    from heddle.contrib.rag.chunker.sentence_chunker import ChunkConfig, chunk_mux_entry

    chunk_cfg = ChunkConfig(target_chars=CHUNK_TARGET, max_chars=CHUNK_MAX)
    all_chunks = []
    t0 = time.perf_counter()
    for entry in stream.entries:
        chunks = chunk_mux_entry(entry, config=chunk_cfg)
        all_chunks.extend(chunks)
    elapsed = time.perf_counter() - t0

    print(f"  Total chunks:    {len(all_chunks)}")
    print(f"  Avg chunk len:   {sum(len(c.text) for c in all_chunks) / max(len(all_chunks), 1):.0f} chars")
    print(f"  Chunk time:      {elapsed:.3f}s")

    # ------------------------------------------------------------------
    # Step 5: Store in DuckDB
    # ------------------------------------------------------------------
    print(f"\n[5/5] Storing chunks in DuckDB ({DB_PATH})...")
    from heddle.contrib.rag.vectorstore.duckdb_store import DuckDBVectorStore
    from heddle.contrib.rag.schemas.embedding import EmbeddedChunk

    store = DuckDBVectorStore(db_path=DB_PATH).initialize()

    if do_embed:
        print("  Embedding via Ollama (this may take a while)...")
        t0 = time.perf_counter()
        count = store.add_chunks(all_chunks, batch_size=64)
        elapsed = time.perf_counter() - t0
        print(f"  Embedded & stored: {count} chunks ({elapsed:.1f}s)")
    else:
        # Store without embeddings — convert TextChunk → EmbeddedChunk with empty embedding
        t0 = time.perf_counter()
        embedded = [
            EmbeddedChunk(
                chunk_id=c.chunk_id,
                source_global_id=c.source_global_id,
                source_channel_id=c.source_channel_id,
                text=c.text,
                embedding=[],
                model="none",
                dimensions=0,
            )
            for c in all_chunks
        ]
        count = store.add_embedded_chunks(embedded)
        elapsed = time.perf_counter() - t0
        print(f"  Stored (no embeddings): {count} chunks ({elapsed:.1f}s)")
        print("  Tip: Run with --embed to generate embeddings via Ollama")

    # Print final stats
    stats = store.stats()
    print(f"\n  Store statistics:")
    for k, v in stats.items():
        print(f"    {k}: {v}")

    store.close()

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    print("\n" + "=" * 70)
    print("  Pipeline complete!")
    print(f"  {stream.channel_count} channels → {stream.total_entries} posts → "
          f"{len(all_chunks)} chunks → DuckDB ({DB_PATH})")
    print("=" * 70)


if __name__ == "__main__":
    main()
