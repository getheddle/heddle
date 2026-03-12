# CLAUDE.md — Loom project context

## What this project is

Loom (Lightweight Orchestrated Operational Mesh) is an actor-based framework for orchestrating multiple LLM agents via NATS messaging. It was built to replace a monolithic AI conversation approach that breaks down as database volume and knowledge graph complexity grow.

The core idea: instead of one big LLM context, split work across narrowly-scoped stateless workers coordinated by an orchestrator through a message bus.

## Project structure

```
src/loom/
  core/         # Message schemas (Pydantic), base actor class, I/O contract validation, workspace manager, config loader
  worker/       # Stateless LLM worker actor, processor worker, LLM backend adapters, knowledge loader, tool-use, embeddings
  orchestrator/ # Orchestrator actor, checkpoint system (Redis), goal decomposer, result synthesizer, pipeline orchestrator
  router/       # Deterministic task router with dead-letter handling and rate limiting (not an LLM — pure logic)
  bus/          # NATS message bus adapter
  cli/          # Click CLI entry point (worker, processor, pipeline, orchestrator, router, submit commands)
  contrib/      # Optional integrations (Django-style contrib namespace)
    duckdb/     # DuckDB tools and backends: DuckDBViewTool, DuckDBVectorTool, DuckDBQueryBackend
configs/
  workers/      # YAML configs defining each worker's system prompt, I/O schema, default tier
  orchestrators/# Orchestrator configs
  router_rules.yaml  # Tier overrides and rate limits (enforced by token-bucket limiter)
k8s/            # Kubernetes manifests (Minikube-ready, Kustomize)
tests/          # Unit tests (messages, contracts, checkpoint, pipeline, workers, processor) and integration test
```

## Key design rules

- **Workers are stateless.** They process one task and reset (via `reset()` hook). No state carries between tasks — this is enforced, not optional.
- **All inter-actor communication uses typed Pydantic messages** (`TaskMessage`, `TaskResult`, `OrchestratorGoal`, `CheckpointState` in `core/messages.py`).
- **The router is deterministic** — it does not use an LLM. It routes by `worker_type` and `model_tier` using rules in `configs/router_rules.yaml`. Unroutable tasks go to `loom.tasks.dead_letter`.
- **Workers have strict I/O contracts** validated by `core/contracts.py`. Input and output schemas are defined per-worker in their YAML config. Boolean values are correctly distinguished from integers.
- **Three model tiers exist:** `local` (Ollama), `standard` (Claude Sonnet etc.), `frontier` (Claude Opus etc.). The router and task metadata decide which tier handles each task.
- **Rate limiting:** Token-bucket rate limiter enforces per-tier dispatch throttling based on `rate_limits` in `router_rules.yaml`.
- **NATS subject convention:**
  - `loom.tasks.incoming` — Router picks up tasks here
  - `loom.tasks.{worker_type}.{tier}` — Routed tasks land here; workers subscribe with queue groups
  - `loom.tasks.dead_letter` — Unroutable/rate-limited tasks land here
  - `loom.results.{goal_id}` — Results flow back to orchestrators
  - `loom.goals.incoming` — Top-level goals for orchestrators

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
loom pipeline --config configs/orchestrators/doc_pipeline.yaml --nats-url nats://localhost:4222

# Submit a test goal
loom submit "some goal text" --nats-url nats://localhost:4222
```

## Current state

All major components are implemented and functional:

- **Core:** Message schemas, contract validation (with correct bool/int handling), base actor (with signal handling and configurable concurrency), config loader (with schema validation).
- **Worker:** LLMWorker with resilient JSON parsing (strips markdown fences, handles preamble), `reset()` hook after each task, knowledge source injection, file-ref resolution via WorkspaceManager, multi-turn tool-use loop, knowledge silo loading/write-back. Backends updated to current Anthropic API version (2024-10-22) with tool-use support (tools/messages params).
- **Tool-Use:** ToolProvider ABC and SyncToolProvider in `worker/tools.py`. Dynamic class loading via `load_tool_provider()`. LLMWorker runs a multi-turn tool execution loop (max 10 rounds) when tools are configured.
- **Knowledge Silos:** Folder-based knowledge injection (`knowledge_silos` config key). Read-only folders prepend content to system prompt. Read-write folders accept `silo_updates` from LLM output (add/modify/delete actions). Tool-type silos load ToolProvider instances for LLM function-calling.
- **Embeddings:** EmbeddingProvider ABC and OllamaEmbeddingProvider in `worker/embeddings.py`. Generates vector embeddings via Ollama `/api/embed` endpoint. Supports single and batch embedding. Lazy dimension detection.
- **Router:** Deterministic routing with dead-letter subject for unroutable tasks, token-bucket rate limiting per tier.
- **Orchestrator:** Full OrchestratorActor with decompose/dispatch/collect/synthesize loop. GoalDecomposer (LLM-based task decomposition), ResultSynthesizer (merge + LLM synthesis modes), CheckpointManager (Redis-backed, configurable TTL).
- **PipelineOrchestrator:** Fully functional sequential stage execution with input mapping, conditions, timeouts.
- **ProcessorWorker:** Non-LLM backend support with BackendError hierarchy and SyncProcessingBackend for CPU-bound backends.
- **WorkspaceManager:** Centralized file-ref resolution with path traversal protection, JSON/text read/write helpers.
- **CLI:** All 6 commands registered (worker, processor, pipeline, orchestrator, router, submit). Tier mismatch warnings on worker startup.
- **Contrib DuckDB:** `loom.contrib.duckdb` — DuckDBViewTool (view-based LLM tool), DuckDBVectorTool (semantic similarity search), DuckDBQueryBackend (action-dispatch query backend with FTS, filtering, stats, get, vector search). All configurable via constructor params. Optional dependency: `pip install loom[duckdb]`.
- **Tests:** 223 unit tests pass (messages, contracts, checkpoint, pipeline, workers, processor, workspace, tools, tool-use, knowledge silos, embeddings, contrib/duckdb). Integration test has `@pytest.mark.integration` marker and polling-based result collection.
- **Infrastructure:** Dockerfiles and k8s manifests updated with correct CMDs and no stale FIXMEs.

## Known issues

- None currently blocking.

## What to implement next

1. **Orchestrator tests** — unit tests for OrchestratorActor (decompose/dispatch/synthesize loop)
2. **End-to-end integration test** — full goal submission through router/workers/orchestrator
3. **Router dead-letter consumer** — implement a dead-letter processor for monitoring/retry

## What NOT to do

- Don't add shared mutable state between workers. Workers are isolated actors.
- Don't put LLM logic in the router. It's deterministic routing only.
- Don't merge worker configs into a single monolithic prompt. Each worker stays narrow.
- Don't skip I/O contract validation — it's the only safety net between actors.
- Workers must always output valid JSON matching their output_schema. The system prompt enforces this.
