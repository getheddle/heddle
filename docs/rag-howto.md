# RAG Pipeline for Social Media Stream Analysis

## Overview

`loom.contrib.rag` is a contrib module for processing social media streams (currently Telegram channels) through a multi-stage pipeline: ingest, normalize, multiplex, chunk, embed, and analyze.

It is designed for Persian/RTL text but works with any language.

## Installation

```bash
pip install loom[rag]

# Or in development mode from the loom repo:
pip install -e ".[rag]"
```

Dependencies added by `[rag]`: `duckdb>=1.0.0`, `requests>=2.31.0`.

For embedding generation you also need a running Ollama server with `nomic-embed-text` (or another model):

```bash
ollama pull nomic-embed-text
```

## Architecture

```
Telegram JSON ──► TelegramIngestor ──► NormalizedPost[]
                                            │
                      ┌─────────────────────┘
                      ▼
                  StreamMux ──────────────► MuxedStream
                  (chronological merge       (entries sorted by timestamp,
                   + time windowing)          assigned to 6h windows)
                      │
                      ▼
              SentenceChunker ──────────► TextChunk[]
                      │
              ┌───────┴───────┐
              ▼               ▼
        DuckDBVectorStore   LLM Analysis Actors
        (embed + store)     (TrendAnalyzer, CorroborationFinder,
                             AnomalyDetector, DataExtractor)
```

## Quick Start (Standalone Python)

The simplest way to use the RAG module — no Loom infrastructure needed:

```python
from datetime import timedelta
from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
from loom.contrib.rag.mux.stream_mux import merge_from_ingestors
from loom.contrib.rag.schemas.mux import MuxWindowConfig
from loom.contrib.rag.chunker.sentence_chunker import ChunkConfig, chunk_mux_entry
from loom.contrib.rag.vectorstore.duckdb_store import DuckDBVectorStore

# 1. Ingest
ingestors = [
    TelegramIngestor("exports/channel_1.json", min_text_len=10).load(),
    TelegramIngestor("exports/channel_2.json", min_text_len=10).load(),
]

# 2. Multiplex
window_config = MuxWindowConfig(window_duration=timedelta(hours=6))
stream = merge_from_ingestors(ingestors, window_config=window_config)
print(f"{stream.total_entries} posts in {len(stream.window_ids)} windows")

# 3. Chunk
cfg = ChunkConfig(target_chars=400, max_chars=600)
chunks = []
for entry in stream.entries:
    chunks.extend(chunk_mux_entry(entry, config=cfg))

# 4. Store + Embed
store = DuckDBVectorStore(
    db_path="/tmp/my-rag.duckdb",
    embedding_model="nomic-embed-text",
).initialize()

stored = store.add_chunks(chunks)  # embeds via Ollama
print(f"Stored {stored} chunks")

# 5. Search
results = store.search("earthquake damage reports", limit=5)
for r in results:
    print(f"  [{r.score:.3f}] {r.text[:80]}...")

store.close()
```

## Module Reference

### Schemas (`loom.contrib.rag.schemas`)

All data models are Pydantic v2 BaseModels.

| Schema | Module | Purpose |
|--------|--------|---------|
| `NormalizedPost` | `schemas.post` | Canonical post representation across all sources |
| `Language` | `schemas.post` | Enum: `fa`, `ar`, `en`, `mixed`, `unknown` |
| `ChannelBias` | `schemas.post` | Enum: `state_media`, `independent`, `fact_check`, etc. |
| `ChannelEditorProfile` | `schemas.post` | Trust weight + bias classification per channel |
| `RawTelegramMessage` | `schemas.telegram` | Raw Telegram JSON message (polymorphic text field) |
| `TelegramChannel` | `schemas.telegram` | Telegram channel container |
| `MuxWindowConfig` | `schemas.mux` | Tumbling/sliding window configuration |
| `MuxEntry` | `schemas.mux` | Single entry in a muxed stream (wraps NormalizedPost) |
| `MuxedStream` | `schemas.mux` | Complete multiplexed stream with window assignments |
| `TextChunk` | `schemas.chunk` | Chunked text segment with provenance |
| `ChunkStrategy` | `schemas.chunk` | Enum: `sentence`, `paragraph`, `whole_post`, `fixed_char` |
| `EmbeddedChunk` | `schemas.embedding` | Chunk with embedding vector |
| `SimilarityResult` | `schemas.embedding` | Search result with cosine similarity score |
| `TrendSignal` | `schemas.analysis` | Detected trend across channels |
| `CorroborationMatch` | `schemas.analysis` | Cross-channel corroboration |
| `AnomalyFlag` | `schemas.analysis` | Statistical or semantic anomaly |
| `ExtractedData` | `schemas.analysis` | Structured data extraction results |

### Ingestion (`loom.contrib.rag.ingestion`)

**TelegramIngestor** — Parses Telegram Desktop JSON exports.

```python
from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor

ingestor = TelegramIngestor(
    source_path="result.json",
    min_text_len=10,       # skip messages shorter than this
).load()

# Properties
ingestor.channel_id    # int
ingestor.channel_name  # str

# Get all posts
posts = ingestor.ingest_all()  # list[NormalizedPost]
```

Handles:
- Polymorphic text fields (string or list of text/entity objects)
- Reaction counts (emoji + paid)
- Forward detection
- Service message filtering
- Media type detection

**DEFAULT_PROFILES** — Pre-configured channel bias profiles:

```python
from loom.contrib.rag.ingestion.telegram_ingestor import DEFAULT_PROFILES

# FarsNews: state_media, trust_weight=0.3
# Iranwire: independent, trust_weight=0.8
# Hamkelasi: educational, trust_weight=0.7
# Factnameh: fact_check, trust_weight=0.9
```

### Text Normalization (`loom.contrib.rag.tools`)

**RTL Normalizer** — Persian/Arabic text normalization:

```python
from loom.contrib.rag.tools.rtl_normalizer import normalize

result = normalize(text)
result.text          # normalized text
result.hashtags      # extracted hashtags
result.mentions      # extracted mentions
result.links         # extracted URLs
result.has_emoji     # bool
```

Features: ZWNJ preservation, Arabic-to-Persian character substitution (ي→ی, ك→ک), digit normalization (٠-٩→0-9, ۰-۹→0-9), emoji handling, Telegram footer stripping.

**Temporal Batcher** — Time-window utilities:

```python
from loom.contrib.rag.tools.temporal_batcher import (
    tumbling_windows, sliding_windows, daily_windows, describe_windows,
)

# Any object with a .timestamp (datetime) attribute works
windows = tumbling_windows(items, duration=timedelta(hours=6))
windows = sliding_windows(items, duration=timedelta(hours=6), step=timedelta(hours=1))
windows = daily_windows(items, tz_offset_hours=3.5)  # Iran Standard Time
```

### Stream Multiplexer (`loom.contrib.rag.mux`)

**StreamMux** — Merges multiple channel streams into chronological order with window assignment:

```python
from loom.contrib.rag.mux.stream_mux import StreamMux, merge_from_ingestors

# Manual usage
mux = StreamMux()
mux.add_stream(channel_1_posts)
mux.add_stream(channel_2_posts)
stream = mux.merge(window_config=MuxWindowConfig())

# Convenience function (from ingestors directly)
stream = merge_from_ingestors(ingestors, window_config=config)

# Access results
stream.total_entries    # int
stream.channel_count    # int
stream.time_span_hours  # float
stream.window_ids       # list[str]
stream.entries          # list[MuxEntry]
stream.windows()        # dict[str, list[MuxEntry]]
stream.window("w1")     # list[MuxEntry] for specific window
```

### Chunker (`loom.contrib.rag.chunker`)

**SentenceChunker** — Persian-aware text chunking:

```python
from loom.contrib.rag.chunker.sentence_chunker import ChunkConfig, chunk_post, chunk_mux_entry

cfg = ChunkConfig(
    target_chars=400,     # soft target
    max_chars=600,        # hard maximum
    overlap_chars=50,     # overlap between chunks
    min_chars=20,         # minimum chunk length
)

# From NormalizedPost
chunks = chunk_post(post, config=cfg)

# From MuxEntry
chunks = chunk_mux_entry(entry, config=cfg)
```

Splitting strategy: paragraphs first, then sentences (handles Persian sentence-enders), then fixed-char fallback.

### Vector Store (`loom.contrib.rag.vectorstore`)

**DuckDBVectorStore** — Embedded vector database:

```python
from loom.contrib.rag.vectorstore.duckdb_store import DuckDBVectorStore

store = DuckDBVectorStore(
    db_path="/tmp/rag.duckdb",
    embedding_model="nomic-embed-text",
    ollama_url="http://localhost:11434",
).initialize()

# Embed and store chunks (calls Ollama)
count = store.add_chunks(text_chunks, batch_size=64)

# Store pre-embedded chunks
count = store.add_embedded_chunks(embedded_chunks)

# Semantic search
results = store.search("earthquake reports", limit=10, channel_ids=[1006939659])

# CRUD
chunk = store.get("1:5:0")
store.delete("1:5:0")
store.delete_by_source("1:5")

# Stats
stats = store.stats()
store.close()
```

Uses `list_cosine_similarity` (not `array_cosine_similarity`) because DuckDB `FLOAT[]` is variable-length.

### Analysis Actors (`loom.contrib.rag.analysis`)

LLM-powered analysis actors for trend detection, cross-channel corroboration, anomaly detection, and data extraction.

```python
from loom.contrib.rag.analysis.llm_analyzers import (
    LLMBackend, TrendAnalyzer, CorroborationFinder,
    AnomalyDetector, DataExtractor,
)

# LLM backend (auto-routes by model prefix)
backend = LLMBackend(
    model="ollama:llama3.2:3b",           # local via Ollama
    # model="anthropic:claude-sonnet-4-6",   # cloud via Anthropic
)

# Trend analysis
analyzer = TrendAnalyzer(backend)
signals = analyzer.analyze(window_entries, window_id="w1",
                           window_start=start, window_end=end)

# Corroboration (cross-channel)
finder = CorroborationFinder(backend)
matches = finder.analyze(window_entries, ...)

# Anomaly detection
detector = AnomalyDetector(backend)
flags = detector.analyze(window_entries, ...)

# Data extraction (statistics, names, dates, locations)
extractor = DataExtractor(backend)
data = extractor.analyze(window_entries, ...)
```

## Loom Pipeline Integration

The RAG module includes Loom backend wrappers and YAML configs for running as distributed Loom workers.

### Backend Wrappers (`loom.contrib.rag.backends`)

| Backend | Worker Type | Wraps |
|---------|------------|-------|
| `IngestorBackend` | processor | TelegramIngestor |
| `MuxBackend` | processor | StreamMux |
| `ChunkerBackend` | processor | SentenceChunker |
| `VectorStoreBackend` | processor | DuckDBVectorStore |

### Worker Configs

Pre-built YAML configs in `configs/workers/`:

```
rag_ingestor.yaml       # Telegram ingestion
rag_mux.yaml            # Stream multiplexing
rag_chunker.yaml        # Sentence chunking
rag_vectorstore.yaml    # Vector store operations
rag_trend_analyzer.yaml # LLM trend analysis
```

### Running with Loom Infrastructure

```bash
# Start NATS
docker run -p 4222:4222 nats:latest

# Start router
loom router --nats-url nats://localhost:4222

# Start workers
loom processor --config configs/workers/rag_ingestor.yaml --nats-url nats://localhost:4222
loom processor --config configs/workers/rag_chunker.yaml --nats-url nats://localhost:4222
loom processor --config configs/workers/rag_vectorstore.yaml --nats-url nats://localhost:4222

# Start pipeline
loom pipeline --config configs/orchestrators/rag_pipeline.yaml --nats-url nats://localhost:4222

# Submit work
loom submit "Ingest telegram export" \
  --context source_path=/data/exports/result-1.json \
  --nats-url nats://localhost:4222
```

### Pipeline Config

`configs/orchestrators/rag_pipeline.yaml` defines a 3-stage pipeline:

```
ingest → chunk → vectorize
```

Each stage maps outputs to the next stage's inputs via `input_mapping`.

## Adding a New Source (non-Telegram)

To support a new data source, create an ingestor that produces `NormalizedPost` objects:

```python
from loom.contrib.rag.schemas.post import NormalizedPost, Language

class MyIngestor:
    def __init__(self, source_path: str):
        self._path = source_path
        self._posts: list[NormalizedPost] = []

    def load(self) -> "MyIngestor":
        # Parse your data format
        for item in self._parse_source():
            self._posts.append(NormalizedPost(
                global_id=f"{self.channel_id}:{item['id']}",
                source_channel_id=self.channel_id,
                source_channel_name=self.channel_name,
                message_id=item["id"],
                timestamp=item["datetime"],  # timezone-aware datetime
                text_clean=item["text"],
                language=Language.PERSIAN,
            ))
        return self

    @property
    def channel_id(self) -> int: ...
    @property
    def channel_name(self) -> str: ...
    def ingest_all(self) -> list[NormalizedPost]:
        return list(self._posts)
```

The ingestor must:
1. Implement `load()` returning `self`
2. Have `channel_id` and `channel_name` properties
3. Have `ingest_all()` returning `list[NormalizedPost]`

Then use it with `merge_from_ingestors()` just like `TelegramIngestor`.

## Testing

```bash
# Run all RAG tests
pytest tests/contrib/rag/ -v

# Run specific module tests
pytest tests/contrib/rag/test_schemas.py -v
pytest tests/contrib/rag/test_ingestion.py -v
pytest tests/contrib/rag/test_mux.py -v
pytest tests/contrib/rag/test_chunker.py -v
pytest tests/contrib/rag/test_tools.py -v
pytest tests/contrib/rag/test_backends.py -v
```

All tests run without infrastructure (no NATS, no Ollama, no DuckDB server). DuckDB runs in-memory for tests.

## Demo

```bash
# Run the full pipeline with real Telegram data (no embeddings)
python examples/rag_demo.py

# With embeddings (requires Ollama running)
python examples/rag_demo.py --embed
```

## File Layout

```
src/loom/contrib/rag/
  __init__.py
  backends.py                    # Loom SyncProcessingBackend wrappers
  schemas/
    __init__.py                  # Re-exports all public schemas
    post.py                      # NormalizedPost, Language, ChannelBias
    telegram.py                  # RawTelegramMessage, TelegramChannel
    mux.py                       # MuxWindowConfig, MuxEntry, MuxedStream
    chunk.py                     # TextChunk, ChunkStrategy
    embedding.py                 # EmbeddedChunk, SimilarityResult
    analysis.py                  # TrendSignal, AnomalyFlag, ExtractedData, etc.
  ingestion/
    __init__.py
    telegram_ingestor.py         # TelegramIngestor + DEFAULT_PROFILES
  mux/
    __init__.py
    stream_mux.py                # StreamMux, merge_from_ingestors
  chunker/
    __init__.py
    sentence_chunker.py          # ChunkConfig, chunk_post, chunk_mux_entry
  vectorstore/
    __init__.py
    duckdb_store.py              # DuckDBVectorStore
  analysis/
    __init__.py
    llm_analyzers.py             # LLMBackend, TrendAnalyzer, etc.
  tools/
    __init__.py
    rtl_normalizer.py            # normalize(), Persian/RTL text processing
    temporal_batcher.py          # tumbling_windows, sliding_windows, daily_windows
```
