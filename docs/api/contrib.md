# Contrib Modules

The `loom.contrib` package contains optional integrations that extend Loom's
capabilities. Each module requires its own optional dependency extra.

| Module | Extra | Purpose |
|--------|-------|---------|
| `contrib.duckdb` | `duckdb` | Embedded analytics and vector search |
| `contrib.lancedb` | `lancedb` | ANN vector search via LanceDB |
| `contrib.redis` | `redis` | Production checkpoint persistence |
| `contrib.rag` | `rag` | Social media stream RAG pipeline |

See [RAG How-To](../rag-howto.md) for the RAG pipeline guide.

## Valkey/Redis Store

Production checkpoint store using Redis/Valkey. Replaces the default
in-memory store for persistent orchestrator checkpoints.

::: loom.contrib.redis.store

## DuckDB Query Backend

Action-dispatch query backend for DuckDB. Supports full-text search,
filtering, statistics, single-row get, and vector similarity search.

::: loom.contrib.duckdb.query_backend

## DuckDB View Tool

Read-only DuckDB view exposed as an LLM-callable tool. Workers can query
structured data during processing.

::: loom.contrib.duckdb.view_tool

## DuckDB Vector Tool

Semantic similarity search via DuckDB embeddings, exposed as an LLM tool.

::: loom.contrib.duckdb.vector_tool

## LanceDB Vector Store

ANN vector storage and search via LanceDB. Faster than DuckDB for large
datasets. Implements the `VectorStore` ABC.

::: loom.contrib.lancedb.store

## LanceDB Vector Tool

Semantic similarity search via LanceDB, exposed as an LLM tool.

::: loom.contrib.lancedb.tool
