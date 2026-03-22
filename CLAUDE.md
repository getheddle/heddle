# CLAUDE.md — Loom project context

## What this project is

Loom (Lightweight Orchestrated Operational Mesh) is an actor-based framework for orchestrating multiple LLM agents via NATS messaging. It was built to replace a monolithic AI conversation approach that breaks down as database volume and knowledge graph complexity grow.

The core idea: instead of one big LLM context, split work across narrowly-scoped stateless workers coordinated by an orchestrator through a message bus.

## Project structure

```text
src/loom/
  core/
    actor.py              # BaseActor — async actor with signal handling, configurable concurrency,
                          #   control subscription (loom.control.reload), on_reload() hook,
                          #   OTel span per message (_process_one)
    config.py             # load_config(), ConfigValidationError, worker/pipeline/orchestrator/router validation
                          #   Input mapping path validation, processing_backend format validation,
                          #   condition operator strict validation
                          #   resolve_schema_refs() — resolve input_schema_ref/output_schema_ref
                          #   to JSON Schema via Pydantic model imports
    contracts.py          # I/O contract validation (bool/int distinction, schema enforcement)
    manifest.py           # AppManifest Pydantic model, validate_app_manifest(), load_manifest()
    messages.py           # Pydantic models: TaskMessage, TaskResult, OrchestratorGoal,
                          #   CheckpointState, ModelTier, TaskStatus; request_id propagation
    workspace.py          # WorkspaceManager — file-ref resolution, path traversal protection

  worker/
    base.py               # TaskWorker base class (abstract)
    runner.py             # LLMWorker — main worker actor (JSON parsing, reset hook, tool-use loop)
                          #   execute_with_tools() — standalone tool-use loop (shared with Workshop)
    backends.py           # LLMBackend ABC + AnthropicBackend, OllamaBackend, OpenAICompatibleBackend
                          #   build_backends_from_env() — resolve backends from env vars
    processor.py          # ProcessorWorker, SyncProcessingBackend ABC (serialize_writes option),
                          #   BackendError hierarchy
    tools.py              # ToolProvider ABC, SyncToolProvider, load_tool_provider(), MAX_TOOL_ROUNDS=10
    knowledge.py          # Knowledge silo loading and write-back (read-only, read-write, tool silos)
    embeddings.py         # EmbeddingProvider ABC, OllamaEmbeddingProvider (Ollama /api/embed)

  orchestrator/
    runner.py             # OrchestratorActor — decompose/dispatch/collect/synthesize loop (concurrent goals via max_concurrent_goals)
    stream.py             # ResultStream — async iterator for streaming result collection (Strategy A)
                          #   on_result callback, early exit, timeout, duplicate filtering
    decomposer.py         # GoalDecomposer — LLM-based task decomposition, WorkerDescriptor
    synthesizer.py        # ResultSynthesizer — merge + LLM synthesis modes
    pipeline.py           # PipelineOrchestrator — dependency-aware parallel stage execution with input mapping
                          #   Incremental parallel stage completion via asyncio.wait(FIRST_COMPLETED)
                          #   Typed error hierarchy: PipelineStageError → Timeout/Validation/Worker/Mapping
                          #   Per-stage retry (max_retries, transient errors only)
                          #   Inter-stage contract validation (input_schema/output_schema on stages)
                          #   Execution timeline (_timeline in output: started_at, ended_at, wall_time_ms)
                          #   LOOM_TRACE env var for full I/O debug logging
                          #   request_id propagation across goal→task→result chain
    checkpoint.py         # CheckpointManager — pluggable store, configurable TTL
    store.py              # CheckpointStore ABC + InMemoryCheckpointStore

  scheduler/
    scheduler.py          # SchedulerActor — cron + interval dispatch of goals/tasks
                          #   expand_from: dotted path to expansion function for multi-session dispatch
    config.py             # Scheduler config validation

  router/
    router.py             # Deterministic task router + token-bucket rate limiter + dead-letter
    dead_letter.py        # DeadLetterConsumer — bounded in-memory store, list/count/clear/replay
                          #   ReplayRecord audit trail (replay_log, replay_count)

  bus/
    base.py               # MessageBus ABC + Subscription ABC
    memory.py             # InMemoryBus + InMemorySubscription (for testing, no infra needed)
    nats_adapter.py       # NATSBus + NATSSubscription (production, queue groups)
                          #   Malformed message skip-and-continue, reconnection event logging

  mcp/
    config.py             # MCP gateway YAML config loading + validation
    discovery.py          # Tool definition generators (worker/pipeline/query → MCP tools)
    bridge.py             # MCPBridge — MCP tool calls → NATS TaskMessage dispatch + result collection
                          #   Pydantic ValidationError catching, progress callback error logging
    resources.py          # WorkspaceResources — workspace files as MCP resources (workspace:/// URIs)
    server.py             # create_server(), MCPGateway, run_stdio(), run_streamable_http()
                          #   MCP progress notifications wired to pipeline stage callbacks
                          #   Workshop tool dispatch, ToolAnnotations (destructiveHint)
    workshop_discovery.py # Workshop MCP tool definitions (workshop.* namespace)
                          #   worker CRUD, test bench, eval, impact, dead-letter tools
    workshop_bridge.py    # WorkshopBridge — direct Workshop component calls (no NATS)
                          #   ConfigManager, WorkerTestRunner, EvalRunner, DeadLetterConsumer

  tracing/
    __init__.py           # Public API: get_tracer, init_tracing, inject/extract_trace_context
    otel.py               # OpenTelemetry integration — optional, graceful no-op when SDK not installed
                          #   W3C traceparent propagation via _trace_context key in NATS messages

  tui/
    __init__.py           # Package init
    app.py                # LoomDashboard — Textual TUI app, live NATS observer (loom.> wildcard)
                          #   Goals/Tasks/Pipeline/Events panels, StatusBar, keybindings (q/c/r)
                          #   DashboardState, TrackedGoal/Task/Stage domain models

  discovery/
    mdns.py               # LoomServiceAdvertiser — mDNS/Bonjour LAN service advertisement

  cli/
    main.py               # Click CLI: worker, processor, pipeline, orchestrator, scheduler,
                          #   router, submit, mcp, workshop, ui, mdns, dead-letter (12 commands)
                          #   --skip-preflight flag on all actor commands
    preflight.py          # Pre-flight checks: NATS connectivity, env vars, config readability

  workshop/               # LLM Worker Workshop — web-based worker builder, test bench, eval tool
    config_impact.py      # Config impact analysis — reverse-map worker→pipelines, downstream stages, risk
    app.py                # FastAPI + HTMX + Jinja2 web application (27 routes, mDNS lifespan)
                          #   Dead-letter inspection UI, backend detection, worker validation endpoint
    app_manager.py        # AppManager — deploy/list/remove app bundles (ZIP upload, reload notify)
                          #   Atomic deployment (temp dir + rename), symlink rejection, path traversal validation
    test_runner.py        # WorkerTestRunner — execute worker configs directly against LLM backends
    db.py                 # WorkshopDB — DuckDB storage for eval results, worker versions, metrics,
                          #   eval baselines (golden dataset regression detection)
    eval_runner.py        # EvalRunner — systematic test suite execution with field_match/exact_match/llm_judge scoring
    config_manager.py     # ConfigManager — CRUD for worker/pipeline YAML configs with versioning + multi-dir
    pipeline_editor.py    # PipelineEditor — insert/swap/branch/remove pipeline stages with dep validation
    templates/            # Jinja2 templates: workers, pipelines, apps, dead_letters (list, detail, deploy)
    static/               # CSS (Pico CSS + custom styles)

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
  CODING_GUIDE.md         # Coding, documentation, and commenting standards
  TROUBLESHOOTING.md      # Common issues and solutions (NATS, workers, pipelines, services)
  DESIGN_INVARIANTS.md    # Non-obvious design decisions and red lines (must-read before structural changes)
  APP_DEPLOYMENT.md       # App bundle format, manifest schema, ZIP deployment guide
  LOCAL_DEPLOYMENT.md     # Local deployment with native process managers
  building-workflows.md   # How to build custom workflows
  rag-howto.md            # RAG pipeline setup guide
  workshop.md             # Workshop web app design, architecture, enhancement guide
  conf.py                 # Sphinx configuration for API docs
  index.md                # Sphinx documentation index
  Makefile                # Sphinx build commands

examples/
  rag_demo.py             # End-to-end RAG pipeline demo

docker/                   # Dockerfiles (orchestrator, router, worker, workshop) + entrypoint.sh
docker-compose.yml        # Local dev stack: NATS + Valkey + Workshop + Router
k8s/                      # Kubernetes manifests (namespace, NATS, Valkey, workers, workshop, Kustomize)
deploy/
  macos/                  # launchd plist files + install/uninstall scripts
  windows/                # NSSM-based Windows service install/uninstall scripts

tests/                    # 68 test files, 1472 unit tests + 1 integration test (90% coverage)
  test_messages.py        test_contracts.py       test_checkpoint.py
  test_worker.py          test_task_worker.py     test_processor_worker.py
  test_tools.py           test_tool_use.py        test_knowledge_silos.py
  test_embeddings.py      test_workspace.py       test_decomposer.py
  test_synthesizer.py     test_orchestrator.py    test_pipeline.py
  test_router.py          test_scheduler.py       test_extract_json.py
  test_backends.py        test_config_validation.py  test_scheduler_config.py
  test_config_shipped.py  test_config_validation_extended.py
  test_store.py           test_actor.py           test_nats_adapter.py
  test_cli.py             test_redis_store.py     test_extract_json_extended.py
  test_contrib_duckdb_query.py  test_contrib_duckdb_vector.py  test_contrib_duckdb_view.py
  test_mcp_config.py      test_mcp_discovery.py   test_mcp_bridge.py
  test_mcp_resources.py   test_mcp_server.py
  test_mcp_workshop_discovery.py  test_mcp_workshop_bridge.py  # Workshop MCP tools
  test_bus_memory.py      test_e2e_operations.py  # InMemoryBus E2E (happy path)
  test_e2e_advanced.py                            # E2E failure paths, timeouts, diamonds
  test_workshop_runner.py test_workshop_db.py     test_workshop_eval.py
  test_workshop_config.py test_workshop_pipeline_editor.py
  test_workshop_app.py                                    # Workshop HTTP routes (baselines, replay log)
  test_app_manifest.py    test_app_manager.py     # App manifest + ZIP deployment safety
  test_reload.py          test_mdns.py            # Config reload, mDNS discovery
  test_scheduler_expansion.py                     # Scheduler expand_from
  test_serialize_writes.py                        # SyncProcessingBackend write lock
  test_tracing.py         test_config_impact.py    # OTel tracing, config impact analysis
  test_schema_ref.py                              # Pydantic schema_ref resolution
  test_result_stream.py                           # ResultStream streaming collection (Strategy A)
  test_tui.py                                     # TUI dashboard domain models and event handlers
  test_dead_letter.py     test_preflight.py       # Dead-letter consumer, CLI pre-flight checks
  test_integration.py                             # @pytest.mark.integration (needs NATS)
  contrib/rag/            # 6 RAG test files (backends, chunker, ingestion, mux, schemas, tools)
```

## Key design rules

- **Workers are stateless.** They process one task and reset (via `reset()` hook). No state carries between tasks — this is enforced, not optional.
- **All inter-actor communication uses typed Pydantic messages** (`TaskMessage`, `TaskResult`, `OrchestratorGoal`, `CheckpointState` in `core/messages.py`).
- **The router is deterministic** — it does not use an LLM. It routes by `worker_type` and `model_tier` using rules in `configs/router_rules.yaml`. Unroutable tasks go to `loom.tasks.dead_letter`.
- **Workers have strict I/O contracts** validated by `core/contracts.py`. Input and output schemas are defined per-worker via inline JSON Schema in YAML or via `input_schema_ref`/`output_schema_ref` pointing to Pydantic models (resolved at load time by `config.resolve_schema_refs()`). Boolean values are correctly distinguished from integers.
- **Three model tiers exist:** `local` (Ollama), `standard` (Claude Sonnet), `frontier` (Claude Opus). The router and task metadata decide which tier handles each task.
- **Three LLM backends:** `AnthropicBackend` (Claude API, version 2024-10-22), `OllamaBackend` (local models), `OpenAICompatibleBackend` (vLLM, llama.cpp, LiteLLM, etc.). All support tool-use.
- **Rate limiting:** Token-bucket rate limiter enforces per-tier dispatch throttling based on `rate_limits` in `router_rules.yaml`.
- **NATS subject convention:**
  - `loom.tasks.incoming` — Router picks up tasks here
  - `loom.tasks.{worker_type}.{tier}` — Routed tasks land here; workers subscribe with queue groups
  - `loom.tasks.dead_letter` — Unroutable/rate-limited tasks land here
  - `loom.results.{goal_id}` — Results flow back to orchestrators
  - `loom.results.default` — Results from standalone tasks (no parent goal)
  - `loom.goals.incoming` — Top-level goals for orchestrators
  - `loom.control.reload` — Config hot-reload signal (broadcast)
  - `loom.scheduler.{name}` — Scheduler health-check subject

## Build and test commands

```bash
# Install all dependencies (Python 3.11+ required, uses uv)
uv sync --all-extras

# Run unit tests (no infrastructure needed — excludes integration tests)
uv run pytest tests/ -v -m "not integration"

# Run ALL tests including integration (needs NATS + workers running)
uv run pytest tests/ -v

# Lint (src + tests)
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Build API documentation (static HTML)
uv run sphinx-build -b html docs/ docs/_build/html

# Run a worker locally (needs NATS running)
uv run loom worker --config configs/workers/summarizer.yaml --tier local --nats-url nats://localhost:4222

# Run the router
uv run loom router --nats-url nats://localhost:4222

# Run the orchestrator
uv run loom orchestrator --config configs/orchestrators/default.yaml --nats-url nats://localhost:4222

# Run a pipeline
uv run loom pipeline --config configs/orchestrators/rag_pipeline.yaml --nats-url nats://localhost:4222

# Run the scheduler (needs NATS running)
uv run loom scheduler --config configs/schedulers/example.yaml --nats-url nats://localhost:4222

# Submit a test goal
uv run loom submit "some goal text" --nats-url nats://localhost:4222

# Run an MCP server (needs NATS + workers running)
uv run loom mcp --config configs/mcp/docman.yaml
uv run loom mcp --config configs/mcp/docman.yaml --transport streamable-http --port 8000

# Run the Workshop web UI (no NATS needed for testing/eval)
uv run loom workshop --port 8080
uv run loom workshop --port 8080 --nats-url nats://localhost:4222  # with live metrics
uv run loom workshop --host 0.0.0.0 --port 8080  # LAN accessible

# Advertise services on LAN via mDNS/Bonjour (requires loom[mdns])
uv run loom mdns --workshop-port 8080 --nats-port 4222

# Docker Compose local stack
docker compose up -d                       # start NATS + Valkey + Workshop + Router
docker compose down                        # stop all services
```

## Optional dependencies

```bash
uv sync --extra redis         # Redis-backed CheckpointStore
uv sync --extra local         # Ollama client for local models
uv sync --extra docproc       # Docling for document extraction (PDF, DOCX)
uv sync --extra duckdb        # DuckDB embedded analytics
uv sync --extra rag           # RAG pipeline (DuckDB + requests for Ollama)
uv sync --extra scheduler     # Cron expression parsing (croniter)
uv sync --extra mcp           # MCP gateway (Model Context Protocol SDK)
uv sync --extra workshop      # Worker Workshop web UI (FastAPI, Jinja2, DuckDB)
uv sync --extra mdns          # mDNS/Bonjour service discovery on LAN (zeroconf)
uv sync --extra tui           # TUI terminal dashboard (Textual)
uv sync --extra otel          # OpenTelemetry distributed tracing (spans, OTLP export)
uv sync --extra docs           # Sphinx API documentation generation
uv sync --all-extras          # All dependencies including dev/test
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

**Workshop tools** — expose Workshop capabilities (worker CRUD, test bench, eval, impact analysis, dead-letter inspection) as MCP tools under the `workshop.*` namespace. These call Workshop components directly (no NATS required):

```yaml
tools:
  workshop:                       # Optional workshop tools section
    configs_dir: "configs/"       # Worker/pipeline config directory
    apps_dir: "~/.loom/apps/"     # Deployed app bundles (optional)
    enable:                       # Tool groups to enable (default: worker,test,eval,impact)
      - worker                    # workshop.worker.{list,get,update}
      - test                      # workshop.worker.test
      - eval                      # workshop.eval.{run,compare}
      - impact                    # workshop.impact.analyze
      - deadletter                # workshop.deadletter.{list,replay} — opt-in only (see below)
```

Workshop tools support MCP `ToolAnnotations` — `workshop.deadletter.replay` is marked `destructiveHint: true`.

**Dead-letter tools are opt-in:** The MCP path creates a local in-memory `DeadLetterConsumer` that is **not** subscribed to the live NATS dead-letter stream. Entries only appear if something stores them into that local consumer. Enable `deadletter` explicitly when pairing with a co-located router or for testing workflows.

**Public API:**

```python
from loom.mcp import create_server, run_stdio, run_streamable_http, MCPGateway
server, gateway = create_server("configs/mcp/docman.yaml")
run_stdio(server, gateway)
```

## Worker Workshop

The Workshop is a web-based tool for the full worker lifecycle: Define → Test → Evaluate → Compare → Deploy. It runs without NATS — testing and evaluation call LLM backends directly.

**Start the Workshop:**

```bash
uv sync --extra workshop
OLLAMA_URL=http://localhost:11434 uv run loom workshop --port 8080
```

**Components:**

- **WorkerTestRunner** (`workshop/test_runner.py`): Execute a worker config against a payload without the actor mesh. Builds the full system prompt (with silo injection), calls the LLM backend directly via `execute_with_tools()`, validates I/O contracts, and returns structured results with timing and token usage.
- **EvalRunner** (`workshop/eval_runner.py`): Run test suites (list of input/expected_output pairs) against a worker config. Supports `field_match`, `exact_match`, and `llm_judge` scoring (uses a separate LLM call to evaluate output quality on correctness/completeness/format criteria). Results persist to DuckDB for cross-version comparison and regression detection via golden dataset baselines.
- **ConfigManager** (`workshop/config_manager.py`): CRUD for worker and pipeline YAML configs with hash-based version tracking in DuckDB.
- **PipelineEditor** (`workshop/pipeline_editor.py`): Insert, remove, swap, or branch pipeline stages. Validates dependencies using `PipelineOrchestrator._infer_dependencies()` and Kahn's topological sort.
- **WorkshopDB** (`workshop/db.py`): DuckDB storage for eval runs, eval results, worker versions, metrics, and eval baselines (golden dataset regression detection via `promote_baseline`/`compare_against_baseline`).
- **Web UI** (`workshop/app.py`): FastAPI + HTMX + Jinja2 with Pico CSS. Worker list/editor, interactive test bench, eval dashboard with per-case results, pipeline editor with dependency graph visualization.

**Test suite format** (YAML):

```yaml
- name: basic_summarization
  input:
    text: "The quick brown fox jumps over the lazy dog."
  expected_output:
    summary: "A fox jumps over a dog."
```

## Scaling and performance

### Orchestrator bottleneck and mitigations

The orchestrator is the throughput bottleneck: all goals funnel through a single actor. Five strategies address this at different levels:

**Implemented (v0.3.0–v0.4.0):**

- **B — Concurrent goal processing.** `OrchestratorActor` reads `max_concurrent_goals` from YAML config and passes it to `BaseActor.max_concurrent`. All mutable state (`conversation_history`, `checkpoint_counter`) is per-goal inside `GoalState` — concurrent goals are fully isolated with no shared mutable data and no locks required. Set `max_concurrent_goals: N` in the orchestrator config to process N goals simultaneously within a single instance.

- **C — Pipeline stage parallelism.** `PipelineOrchestrator` now auto-infers stage dependencies from `input_mapping` paths and builds execution levels using Kahn's topological sort. Stages within the same level run concurrently via `asyncio.gather`. Existing configs with genuinely sequential dependencies (like Docman's pipeline) produce the same execution order — no config changes needed. To benefit, design pipelines where independent stages reference only `goal.*` paths or shared earlier stages. `PipelineOrchestrator` also supports `max_concurrent_goals` in config (like `OrchestratorActor`), enabling multiple pipeline goals to run concurrently within a single instance.

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

- **A — Streaming result collection.** ✅ **Implemented (v0.7.0).** `ResultStream` in `orchestrator/stream.py` yields results as they arrive via async iteration. `OrchestratorActor._collect_results()` now uses `ResultStream` with optional `on_result` callback for progress notifications and early exit. `PipelineOrchestrator` parallel levels now use `asyncio.wait(FIRST_COMPLETED)` for incremental stage progress reporting.
- **D — Worker-side batching.** Batch multiple similar tasks into a single LLM call. Would reduce API call overhead for high-volume identical worker types. Requires a batching layer between the router and workers.
- **E — Decomposition caching.** Cache goal decomposition plans for structurally similar goals. Would skip the decomposition LLM call for repeated goal patterns. Requires a cache keyed by goal structure fingerprints.

### MCP gateway considerations

The MCP gateway (`loom/mcp/`) bridges external MCP clients to the LOOM actor mesh. Current state and needed improvements:

- **Pipeline parallelism (C) already benefits MCP.** The `MCPBridge.call_pipeline()` dispatches a goal and the pipeline runs stages concurrently. The bridge's `_collect_pipeline_results()` correctly filters intermediate stage results from the final result.
- **Concurrent MCP calls are supported** — the bridge is fully async. Multiple MCP clients can call tools simultaneously. However, if all calls target the same single-instance orchestrator, they queue at the orchestrator's semaphore.
- **PipelineOrchestrator supports `max_concurrent_goals`** — like `OrchestratorActor`, the pipeline orchestrator reads this config and passes it to `BaseActor.max_concurrent`. Set `max_concurrent_goals: N` in pipeline config to process N goals simultaneously. Pipeline execution is stateless per-goal (local `context` dict), so concurrent goals are naturally isolated.
- **MCP progress notifications** — the server wires `MCPBridge.call_pipeline()` progress_callback to MCP progress tokens. MCP clients with `progressToken` in their request metadata see per-stage progress during pipeline execution.

## Known issues

- None currently blocking.

## Robustness and observability (v0.5.0)

**P1 — Robustness:**

- **Inter-stage contract validation** — pipeline stages can declare `input_schema`/`output_schema` for validation between stages
- **Typed pipeline errors** — `PipelineStageError` hierarchy: `PipelineTimeoutError`, `PipelineValidationError`, `PipelineWorkerError`, `PipelineMappingError`
- **Per-stage retry** — configurable `max_retries` per stage (transient errors only: timeout, worker errors)
- **NATS adapter hardening** — malformed messages are logged and skipped (not crashed), reconnection events logged with structured data
- **MCP bridge hardening** — catches `pydantic.ValidationError`, logs progress callback errors, debug logging for intermediate results
- **Atomic ZIP deployment** — extracts to temp dir then renames; rejects symlinks and path traversal in config paths

**P2 — Observability:**

- **request_id propagation** — `TaskMessage` and `OrchestratorGoal` carry `request_id` through goal→task→result chain; structured log bindings per goal
- **I/O tracing** — `LOOM_TRACE=1` env var enables full input/output logging; `_summarize()` helper truncates by default
- **Dead-letter consumer** — `DeadLetterConsumer` actor with bounded in-memory store (default 1000), list/count/clear/replay via CLI (`loom dead-letter monitor`) and Workshop UI (`/dead-letters`)
- **Pipeline execution timeline** — each pipeline output includes `_timeline` with per-stage `started_at`, `ended_at`, `wall_time_ms`

**P3 — Developer experience:**

- **CLI pre-flight checks** — `check_nats_connectivity()`, `check_env_vars()`, `check_config_readable()` run before actor startup; skip with `--skip-preflight`
- **Workshop UI improvements** — worker search/filter, backend availability badges, inline config validation (`/workers/{name}/validate`), deploy spinner, dead-letter inspection page
- **Config validation** — input_mapping path validation, processing_backend dotted-path format, condition operator strict allowlist
- **Troubleshooting guide** — `docs/TROUBLESHOOTING.md` covering NATS, workers, pipelines, router, Workshop, Docker/K8s, macOS/Windows services
- **Deploy script improvements** — macOS `install.sh` and Windows `install.ps1` with pre-flight checks, NATS connectivity test, post-install health check

## Evaluation, tracing, and config tooling (v0.6.0)

**Evaluation framework:**

- **LLM-as-judge scoring** — `EvalRunner.run_suite(scoring="llm_judge")` uses a separate LLM call to evaluate worker output quality on correctness, completeness, and format compliance criteria (0-to-1 scale with reasoning); customizable via `judge_prompt` parameter
- **Golden dataset regression baselines** — `WorkshopDB.promote_baseline()` marks an eval run as the reference for a worker; `compare_against_baseline()` auto-compares new runs against the baseline; Workshop UI shows regression/improvement per case on the eval detail page
- **Dead-letter replay audit trail** — `ReplayRecord` tracks all replayed entries with timestamps and original failure reason; `replay_log()`, `replay_count()` on `DeadLetterConsumer`; Workshop dead-letters page shows replay history

**Distributed tracing:**

- **OpenTelemetry integration** — optional `otel` extra (`uv sync --extra otel`); `loom.tracing` module with `get_tracer()`, `init_tracing()`, `inject_trace_context()`, `extract_trace_context()`; graceful no-op when OTel SDK not installed
- **Span instrumentation** — spans on `BaseActor._process_one()`, `TaskRouter.route()`, `PipelineOrchestrator._execute_stage()`, `MCPBridge._dispatch_and_wait()`, `OrchestratorActor` phases (decompose/dispatch/collect/synthesize), `execute_with_tools()` LLM calls and tool continuations
- **GenAI semantic conventions** — LLM call spans include `gen_ai.system`, `gen_ai.request.model`, `gen_ai.response.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, `gen_ai.request.temperature`, `gen_ai.request.max_tokens` per the OTel GenAI semantic conventions. Legacy `llm.*` attributes preserved. Set `LOOM_TRACE_CONTENT=1` to record prompt/completion text as span events.
- **W3C traceparent propagation** — trace context propagated through NATS messages via `_trace_context` key; spans link across actor boundaries for end-to-end pipeline tracing

**TUI dashboard:**

- **Terminal dashboard** — `loom ui` command launches a Textual-based terminal UI for real-time NATS observation
- **Four panels** — Goals (status, subtask count, elapsed), Tasks (worker type, tier, model, elapsed), Pipeline (stage execution with wall time), Events (scrolling log of all `loom.>` messages)
- **Read-only observer** — subscribes to `loom.>` wildcard, never publishes; safe to run alongside production actors
- **Keybindings** — `q` quit, `c` clear log, `r` refresh tables

**Config tooling:**

- **Config impact analysis** — `workshop/config_impact.py` reverse-maps worker→pipelines/stages, finds transitive downstream dependencies, assesses breaking-change risk based on output_schema presence
- **Impact panel in Workshop** — HTMX-loaded panel on worker detail page shows affected pipelines, direct stages, downstream stages, risk level; loads async via `/workers/{name}/impact-panel`
- **JSON API** — `GET /workers/{name}/impact` returns full impact analysis as JSON for programmatic use

## App deployment

Loom apps (like baft, docman) can be deployed as ZIP bundles via the Workshop UI.
Each bundle contains a `manifest.yaml`, configs, and optional scripts/Python packages.

**Deploy flow:**

1. Build a ZIP: `bash scripts/build-app.sh` (in the app repo)
2. Upload at Workshop `/apps` page
3. App configs appear in Workers/Pipelines lists
4. Running actors auto-reload via `loom.control.reload` NATS subject

**Manifest schema:** See `loom.core.manifest.AppManifest` or `docs/APP_DEPLOYMENT.md`.

**Apps directory:** `~/.loom/apps/{app_name}/` (configurable via `--apps-dir`)

## Concurrent multi-user sessions

Loom supports multiple users (e.g., two analysts on Claude Desktop) working simultaneously:

- **Pipeline orchestrators** set `max_concurrent_goals: N` in config to process N goals in parallel. Goals are isolated (per-goal context dict, no shared state).
- **Workers** scale via NATS queue groups — run multiple replicas for load balancing.
- **MCP gateway** is fully async — multiple clients can call tools simultaneously.
- **Scheduler expansion** (`expand_from` in schedule config) dispatches one task per active session. The expansion function returns a list of context dicts, each merged into the task payload.
- **DuckDB write serialization** — `SyncProcessingBackend(serialize_writes=True)` wraps calls in an `asyncio.Lock` to prevent concurrent writes to single-writer stores. Run a single DE processor instance for safe serialized writes.

## What to implement next

1. **Workshop MetricsCollector** — optional NATS subscriber for live worker metrics in Workshop dashboard
2. **Worker-side batching (Strategy D)** — batch similar tasks into single LLM calls
3. **Decomposition caching (Strategy E)** — cache decomposition plans for repeated goal patterns

## What NOT to do

- Don't add shared mutable state between workers. Workers are isolated actors.
- Don't put LLM logic in the router. It's deterministic routing only.
- Don't merge worker configs into a single monolithic prompt. Each worker stays narrow.
- Don't skip I/O contract validation — it's the only safety net between actors.
- Workers must always output valid JSON matching their output_schema. The system prompt enforces this.
