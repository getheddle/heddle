# CLAUDE.md — Loom project context

## What this project is

Loom (Lightweight Orchestrated Operational Mesh) is an actor-based framework for orchestrating multiple LLM agents via NATS messaging. It was built to replace a monolithic AI conversation approach that breaks down as database volume and knowledge graph complexity grow.

The core idea: instead of one big LLM context, split work across narrowly-scoped stateless workers coordinated by an orchestrator through a message bus.

## Project structure

```
src/loom/
  core/
    actor.py              # BaseActor — async actor with signal handling, configurable concurrency
    config.py             # load_config(), ConfigValidationError, YAML schema validation
    contracts.py          # I/O contract validation (bool/int distinction, schema enforcement)
    messages.py           # Pydantic models: TaskMessage, TaskResult, OrchestratorGoal,
                          #   CheckpointState, ModelTier, TaskStatus
    workspace.py          # WorkspaceManager — file-ref resolution, path traversal protection

  worker/
    base.py               # TaskWorker base class (abstract)
    runner.py             # LLMWorker — main worker actor (JSON parsing, reset hook, tool-use loop)
    backends.py           # LLMBackend ABC + AnthropicBackend, OllamaBackend, OpenAICompatibleBackend
    processor.py          # ProcessorWorker, SyncProcessingBackend ABC, BackendError hierarchy
    tools.py              # ToolProvider ABC, SyncToolProvider, load_tool_provider(), MAX_TOOL_ROUNDS=10
    knowledge.py          # Knowledge silo loading and write-back (read-only, read-write, tool silos)
    embeddings.py         # EmbeddingProvider ABC, OllamaEmbeddingProvider (Ollama /api/embed)

  orchestrator/
    runner.py             # OrchestratorActor — decompose/dispatch/collect/synthesize loop (concurrent goals via max_concurrent_goals)
    decomposer.py         # GoalDecomposer — LLM-based task decomposition, WorkerDescriptor
    synthesizer.py        # ResultSynthesizer — merge + LLM synthesis modes
    pipeline.py           # PipelineOrchestrator — dependency-aware parallel stage execution with input mapping
    checkpoint.py         # CheckpointManager — pluggable store, configurable TTL
    store.py              # CheckpointStore ABC + InMemoryCheckpointStore

  scheduler/
    scheduler.py          # SchedulerActor — cron + interval dispatch of goals/tasks
    config.py             # Scheduler config validation

  router/
    router.py             # Deterministic task router + token-bucket rate limiter + dead-letter

  bus/
    base.py               # MessageBus ABC + Subscription ABC
    memory.py             # InMemoryBus + InMemorySubscription (for testing, no infra needed)
    nats_adapter.py       # NATSBus + NATSSubscription (production, queue groups)

  mcp/
    config.py             # MCP gateway YAML config loading + validation
    discovery.py          # Tool definition generators (worker/pipeline/query → MCP tools)
    bridge.py             # MCPBridge — MCP tool calls → NATS TaskMessage dispatch + result collection
    resources.py          # WorkspaceResources — workspace files as MCP resources (workspace:/// URIs)
    server.py             # create_server(), MCPGateway, run_stdio(), run_streamable_http()

  cli/
    main.py               # Click CLI: worker, processor, pipeline, orchestrator, scheduler,
                          #   router, submit, mcp (8 commands)

  contrib/                # Optional integrations (Django-style contrib namespace)
    duckdb/
      query_backend.py    # DuckDBQueryBackend — action-dispatch query (FTS, filter, stats, get, vector)
      view_tool.py        # DuckDBViewTool — read-only view as LLM-callable tool
      vector_tool.py      # DuckDBVectorTool — semantic similarity search via embeddings
    redis/
      store.py            # RedisCheckpointStore — production checkpoint persistence
    rag/
      backends.py         # Processor backends: IngestorBackend, MuxBackend, ChunkerBackend,
                          #   VectorStoreBackend
      ingestion/
        telegram_ingestor.py  # TelegramIngestor — parse Telegram JSON exports
      mux/
        stream_mux.py     # StreamMux — merge multi-channel posts with time windows
      chunker/
        sentence_chunker.py   # ChunkConfig, sentence-level text chunking
      vectorstore/
        duckdb_store.py   # DuckDBVectorStore — vector storage and cosine similarity search
      analysis/
        llm_analyzers.py  # TrendAnalyzer, CorroborationFinder, AnomalyDetector, DataExtractor
      schemas/            # Pydantic schemas: post, telegram, mux, chunk, embedding, analysis
      tools/
        rtl_normalizer.py # RTL text normalization tool
        temporal_batcher.py   # Time-window batching tool

configs/
  workers/                # Worker YAML configs (system prompt, I/O schema, tier, timeout)
    summarizer.yaml       #   text → summary + key_points (local tier)
    classifier.yaml       #   text + categories → category + confidence (local tier)
    extractor.yaml        #   text + fields → extracted data (standard tier)
    rag_ingestor.yaml     #   source_path → posts (processor, local)
    rag_mux.yaml          #   posts_by_channel → muxed windows (processor, local)
    rag_chunker.yaml      #   posts → chunks (processor, local)
    rag_vectorstore.yaml  #   action + chunks/query → store/search results (processor, local)
    rag_trend_analyzer.yaml   # posts + window_id → trend analysis (LLM, standard)
    _template.yaml        #   template for new workers
  orchestrators/
    default.yaml          # General-purpose orchestrator (LLM-driven goal decomposition)
    rag_pipeline.yaml     # RAG pipeline: ingest → chunk → vectorize
  schedulers/
    example.yaml          # Example cron + interval schedule definitions
  mcp/
    docman.yaml           # Example: document management MCP server config
  router_rules.yaml       # Tier overrides and per-tier rate limits

docs/                     # Project documentation
  ARCHITECTURE.md         # System architecture overview
  GETTING_STARTED.md      # Quickstart guide
  KUBERNETES.md           # Kubernetes deployment guide
  CONTRIBUTING.md         # Contribution guidelines
  building-workflows.md   # How to build custom workflows
  rag-howto.md            # RAG pipeline setup guide

examples/
  rag_demo.py             # End-to-end RAG pipeline demo

docker/                   # Dockerfiles (orchestrator, router, worker) + entrypoint.sh
k8s/                      # Kubernetes manifests (namespace, NATS, Redis, workers, Kustomize)

tests/                    # 32 test files, 519 unit tests + 1 integration test
  test_messages.py        test_contracts.py       test_checkpoint.py
  test_worker.py          test_task_worker.py     test_processor_worker.py
  test_tools.py           test_tool_use.py        test_knowledge_silos.py
  test_embeddings.py      test_workspace.py       test_decomposer.py
  test_synthesizer.py     test_orchestrator.py    test_pipeline.py
  test_router.py          test_scheduler.py
  test_contrib_duckdb_query.py  test_contrib_duckdb_vector.py  test_contrib_duckdb_view.py
  test_mcp_config.py      test_mcp_discovery.py   test_mcp_bridge.py
  test_mcp_resources.py   test_mcp_server.py
  test_integration.py                             # @pytest.mark.integration (needs NATS)
  contrib/rag/            # 6 RAG test files (backends, chunker, ingestion, mux, schemas, tools)
```

## Key design rules

- **Workers are stateless.** They process one task and reset (via `reset()` hook). No state carries between tasks — this is enforced, not optional.
- **All inter-actor communication uses typed Pydantic messages** (`TaskMessage`, `TaskResult`, `OrchestratorGoal`, `CheckpointState` in `core/messages.py`).
- **The router is deterministic** — it does not use an LLM. It routes by `worker_type` and `model_tier` using rules in `configs/router_rules.yaml`. Unroutable tasks go to `loom.tasks.dead_letter`.
- **Workers have strict I/O contracts** validated by `core/contracts.py`. Input and output schemas are defined per-worker in their YAML config. Boolean values are correctly distinguished from integers.
- **Three model tiers exist:** `local` (Ollama), `standard` (Claude Sonnet), `frontier` (Claude Opus). The router and task metadata decide which tier handles each task.
- **Three LLM backends:** `AnthropicBackend` (Claude API, version 2024-10-22), `OllamaBackend` (local models), `OpenAICompatibleBackend` (vLLM, llama.cpp, LiteLLM, etc.). All support tool-use.
- **Rate limiting:** Token-bucket rate limiter enforces per-tier dispatch throttling based on `rate_limits` in `router_rules.yaml`.
- **NATS subject convention:**
  - `loom.tasks.incoming` — Router picks up tasks here
  - `loom.tasks.{worker_type}.{tier}` — Routed tasks land here; workers subscribe with queue groups
  - `loom.tasks.dead_letter` — Unroutable/rate-limited tasks land here
  - `loom.results.{goal_id}` — Results flow back to orchestrators
  - `loom.goals.incoming` — Top-level goals for orchestrators
  - `loom.scheduler.{name}` — Scheduler health-check subject

## Build and test commands

```bash
# Create venv and install (Python 3.11+ required)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run unit tests (no infrastructure needed — excludes integration tests)
pytest tests/ -v -m "not integration"

# Run ALL tests including integration (needs NATS + workers running)
pytest tests/ -v

# Lint
ruff check src/

# Run a worker locally (needs NATS running)
loom worker --config configs/workers/summarizer.yaml --tier local --nats-url nats://localhost:4222

# Run the router
loom router --nats-url nats://localhost:4222

# Run the orchestrator
loom orchestrator --config configs/orchestrators/default.yaml --nats-url nats://localhost:4222

# Run a pipeline
loom pipeline --config configs/orchestrators/rag_pipeline.yaml --nats-url nats://localhost:4222

# Run the scheduler (needs NATS running, optional: pip install loom[scheduler])
loom scheduler --config configs/schedulers/example.yaml --nats-url nats://localhost:4222

# Submit a test goal
loom submit "some goal text" --nats-url nats://localhost:4222

# Run an MCP server (needs NATS + workers running, optional: pip install loom[mcp])
loom mcp --config configs/mcp/docman.yaml
loom mcp --config configs/mcp/docman.yaml --transport streamable-http --port 8000
```

## Optional dependencies

```bash
pip install loom[redis]       # Redis-backed CheckpointStore
pip install loom[local]       # Ollama client for local models
pip install loom[docproc]     # Docling for document extraction (PDF, DOCX)
pip install loom[duckdb]      # DuckDB embedded analytics
pip install loom[rag]         # RAG pipeline (DuckDB + requests for Ollama)
pip install loom[scheduler]   # Cron expression parsing (croniter)
pip install loom[mcp]         # MCP gateway (Model Context Protocol SDK)
pip install loom[dev]         # All dev/test dependencies
```

## MCP gateway

Any LOOM system can become an MCP server with a single YAML config — zero MCP-specific code needed.

**Config structure** (`configs/mcp/docman.yaml`):
```yaml
name: "docman"
nats_url: "nats://localhost:4222"
tools:
  workers:                    # Each worker config → one MCP tool
    - config: "configs/workers/summarizer.yaml"
    - config: "configs/workers/classifier.yaml"
      name: "classify_document"          # Optional name/description override
      description: "Classify document type"
  pipelines:                  # Each pipeline config → one MCP tool
    - config: "configs/orchestrators/rag_pipeline.yaml"
      name: "ingest_document"            # Required (pipeline has no natural tool name)
  queries:                    # Each backend action → one MCP tool
    - backend: "loom.contrib.duckdb.query_backend.DuckDBQueryBackend"
      actions: ["search", "filter", "stats", "get"]
      name_prefix: "docs"               # → docs_search, docs_filter, etc.
      backend_config:
        db_path: "/tmp/docman-workspace/docman.duckdb"
resources:
  workspace_dir: "/tmp/docman-workspace"
  patterns: ["*.pdf", "*.json"]
```

**Tool discovery flow:** Worker YAML `name` + `input_schema` + `description` → MCP tool definition. Pipeline `input_mapping` `goal.context.*` fields → tool input schema. Query backend `_get_handlers()` → per-action tools with auto-generated schemas.

**Public API:**
```python
from loom.mcp import create_server, run_stdio, run_streamable_http, MCPGateway
server, gateway = create_server("configs/mcp/docman.yaml")
run_stdio(server, gateway)
```

## Scaling and performance

### Orchestrator bottleneck and mitigations

The orchestrator is the throughput bottleneck: all goals funnel through a single actor. Five strategies address this at different levels:

**Implemented (v0.3.0):**

- **B — Concurrent goal processing.** `OrchestratorActor` reads `max_concurrent_goals` from YAML config and passes it to `BaseActor.max_concurrent`. An `asyncio.Lock` protects shared state (`_conversation_history`, `_checkpoint_counter`). Set `max_concurrent_goals: N` in the orchestrator config to process N goals simultaneously within a single instance.

- **C — Pipeline stage parallelism.** `PipelineOrchestrator` now auto-infers stage dependencies from `input_mapping` paths and builds execution levels using Kahn's topological sort. Stages within the same level run concurrently via `asyncio.gather`. Existing configs with genuinely sequential dependencies (like Docman's pipeline) produce the same execution order — no config changes needed. To benefit, design pipelines where independent stages reference only `goal.*` paths or shared earlier stages.

**Free horizontal scaling (no code changes needed):**

NATS queue groups provide horizontal scaling with zero code changes. Run multiple instances of any actor and they automatically load-balance:

```bash
# Run 3 summarizer replicas — NATS distributes tasks across them
loom worker --config configs/workers/summarizer.yaml --tier local &
loom worker --config configs/workers/summarizer.yaml --tier local &
loom worker --config configs/workers/summarizer.yaml --tier local &

# Run 2 pipeline orchestrator replicas
loom pipeline --config configs/orchestrators/my_pipeline.yaml &
loom pipeline --config configs/orchestrators/my_pipeline.yaml &
```

Workers subscribe with queue groups by default (`loom.tasks.{worker_type}.{tier}`). Pipeline orchestrators subscribe to `loom.goals.incoming` with queue groups. Each message is delivered to exactly one replica. This is the preferred scaling path — it preserves per-message isolation without shared state.

In Kubernetes, scale replicas via `kubectl scale deployment/loom-worker --replicas=N` or HPA auto-scaling.

**Not yet implemented (future work):**

- **A — Streaming result collection.** Process subtask results as they arrive rather than waiting for all. Would reduce end-to-end latency for goals with many independent subtasks. Requires changing the collect phase in `OrchestratorActor` to a streaming model.
- **D — Worker-side batching.** Batch multiple similar tasks into a single LLM call. Would reduce API call overhead for high-volume identical worker types. Requires a batching layer between the router and workers.
- **E — Decomposition caching.** Cache goal decomposition plans for structurally similar goals. Would skip the decomposition LLM call for repeated goal patterns. Requires a cache keyed by goal structure fingerprints.

### MCP gateway considerations

The MCP gateway (`loom/mcp/`) bridges external MCP clients to the LOOM actor mesh. Current state and needed improvements:

- **Pipeline parallelism (C) already benefits MCP.** The `MCPBridge.call_pipeline()` dispatches a goal and the pipeline runs stages concurrently. The bridge's `_collect_pipeline_results()` correctly filters intermediate stage results from the final result.
- **Concurrent MCP calls are supported** — the bridge is fully async. Multiple MCP clients can call tools simultaneously. However, if all calls target the same single-instance orchestrator, they queue at the orchestrator's semaphore.
- **PipelineOrchestrator needs `max_concurrent_goals`** — unlike `OrchestratorActor`, the pipeline orchestrator doesn't yet read this config. This means pipeline MCP calls still process one goal at a time per instance. Use horizontal scaling (multiple pipeline instances) as the workaround.
- **MCP progress notifications** — the bridge has a `progress_callback` parameter but the MCP server doesn't wire it to MCP progress tokens yet. This would let MCP clients show per-stage progress during pipeline execution.

## Known issues

- None currently blocking.

## What to implement next

1. **End-to-end integration test** — full goal submission through router/workers/orchestrator
2. **Router dead-letter consumer** — implement a dead-letter processor for monitoring/retry
3. **PipelineOrchestrator concurrent goals** — read `max_concurrent_goals` from pipeline config (like OrchestratorActor does)
4. **MCP progress notifications** — wire `MCPBridge.call_pipeline()` progress_callback to MCP progress tokens
5. **Streaming result collection (Strategy A)** — process subtask results as they arrive
6. **Worker-side batching (Strategy D)** — batch similar tasks into single LLM calls
7. **Decomposition caching (Strategy E)** — cache decomposition plans for repeated goal patterns

## What NOT to do

- Don't add shared mutable state between workers. Workers are isolated actors.
- Don't put LLM logic in the router. It's deterministic routing only.
- Don't merge worker configs into a single monolithic prompt. Each worker stays narrow.
- Don't skip I/O contract validation — it's the only safety net between actors.
- Workers must always output valid JSON matching their output_schema. The system prompt enforces this.
