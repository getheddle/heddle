# Worker

The `loom.worker` package implements the two types of Loom workers:

- **LLM Workers** (`runner.py`) — call language models with system prompts,
  tool-use loops, and JSON parsing. Used for summarization, classification,
  extraction, and analysis tasks.
- **Processor Workers** (`processor.py`) — run arbitrary Python code (no LLM).
  Used for data transformation, ingestion, and integration tasks.

Both types are stateless: they process one task, return a result, and reset.

See [Building Workflows](../building-workflows.md) for the user-facing guide.

## Base

Abstract base class for all workers (`TaskWorker`).

::: loom.worker.base

## Runner

`LLMWorker` — the main LLM worker actor. Includes `execute_with_tools()`,
the standalone tool-use loop shared with the Workshop test bench.

::: loom.worker.runner

## Backends

LLM backend implementations: `AnthropicBackend`, `OllamaBackend`,
`OpenAICompatibleBackend`. Plus `build_backends_from_env()` for automatic
backend detection from environment variables and `~/.loom/config.yaml`.

::: loom.worker.backends

## Processor

`ProcessorWorker` and `SyncProcessingBackend` ABC for non-LLM workers.
Includes `serialize_writes` option and `BackendError` hierarchy.

::: loom.worker.processor

## Tools

`ToolProvider` ABC and `SyncToolProvider` for LLM function-calling tools.
Workers can expose tools that the LLM calls during processing (max 10 rounds).

::: loom.worker.tools

## Knowledge

Knowledge silo loading, injection into system prompts, and write-back.
Supports read-only, read-write, and tool-based knowledge sources.

::: loom.worker.knowledge

## Embeddings

`EmbeddingProvider` ABC and `OllamaEmbeddingProvider` for text embedding
generation via Ollama's `/api/embed` endpoint.

::: loom.worker.embeddings
