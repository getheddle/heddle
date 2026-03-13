# Architecture

**Loom — Lightweight Orchestrated Operational Mesh**

---

## Overview

Loom is an actor-based framework where narrowly-scoped stateless workers are
coordinated by an orchestrator through a NATS message bus. The router handles
deterministic task dispatch with rate limiting. Workers call LLM backends or
run processing backends, validate I/O against JSON Schema contracts, and
publish results back to the orchestrator.

---

## Source Tree

```
src/loom/
├── core/
│   ├── messages.py      # Pydantic schemas: TaskMessage, TaskResult, OrchestratorGoal, CheckpointState
│   ├── actor.py         # Base actor class (NATS subscribe/publish lifecycle)
│   ├── contracts.py     # Lightweight JSON Schema validation for worker I/O
│   ├── workspace.py     # File-ref resolution with path traversal protection
│   └── config.py        # YAML config loader with schema validation
│
├── worker/
│   ├── runner.py        # LLM worker: validate → resolve files → inject knowledge → call LLM → tool loop → validate → publish
│   ├── processor.py     # Non-LLM worker: ProcessingBackend, SyncProcessingBackend, BackendError
│   ├── backends.py      # LLM adapters: Anthropic, Ollama, OpenAI-compatible (with tool-use support)
│   ├── tools.py         # ToolProvider ABC, SyncToolProvider, dynamic tool loader
│   ├── knowledge.py     # Knowledge sources + knowledge silos (folder read/write, tool injection)
│   └── embeddings.py    # EmbeddingProvider ABC, OllamaEmbeddingProvider (/api/embed)
│
├── orchestrator/
│   ├── runner.py        # Orchestrator actor: decompose → dispatch → collect → synthesize
│   ├── pipeline.py      # Pipeline orchestrator: sequential stage execution with input mapping
│   ├── checkpoint.py    # Self-summarization: compresses orchestrator context to Redis snapshots
│   ├── decomposer.py    # LLM-driven goal → subtask decomposition with worker manifest grounding
│   └── synthesizer.py   # Multi-result aggregation (deterministic merge + LLM synthesis modes)
│
├── router/
│   └── router.py        # Deterministic task routing with dead-letter handling and rate limiting
│
├── bus/
│   ├── base.py          # MessageBus ABC, Subscription ABC
│   ├── memory_bus.py    # InMemoryBus for testing (no infrastructure needed)
│   └── nats_adapter.py  # NATS pub/sub/request wrapper
│
├── cli/
│   └── main.py          # Click CLI: worker, processor, pipeline, orchestrator, router, submit
│
└── contrib/
    ├── duckdb/          # DuckDB tools and backends (optional: pip install loom[duckdb])
    ├── redis/           # Redis-backed CheckpointStore (optional: pip install loom[redis])
    └── rag/             # RAG pipeline: ingestion, chunking, embedding, analysis

configs/
├── workers/
│   ├── _template.yaml   # Copy this to create new workers
│   ├── summarizer.yaml  # Text → structured summary (local tier)
│   ├── classifier.yaml  # Text → category with confidence (local tier)
│   └── extractor.yaml   # Text → structured fields (standard tier)
├── orchestrators/
│   └── default.yaml     # General-purpose orchestrator config
└── router_rules.yaml    # Tier overrides and rate limits

docs/                     # Documentation
k8s/                      # Kubernetes manifests (Minikube-ready)
tests/                    # Unit + integration tests
```

---

## How the Pieces Connect

1. **You submit a goal** via CLI or publish to `loom.goals.incoming`
2. **The orchestrator** decomposes it into subtasks (via LLM-driven GoalDecomposer), each targeting a `worker_type`
3. **The router** picks up tasks from `loom.tasks.incoming`, resolves the model tier, enforces rate limits, and publishes to `loom.tasks.{worker_type}.{tier}` (unroutable tasks go to `loom.tasks.dead_letter`)
4. **Workers** (competing consumers via NATS queue groups) pick up tasks, call the appropriate LLM backend, validate the output, and publish results to `loom.results.{goal_id}`
5. **The orchestrator** collects results, decides if more subtasks are needed, and eventually produces a final answer

Workers are stateless — they reset after every task. The orchestrator is longer-lived
but checkpoints itself to Redis when its context grows too large, compressing history
into a structured summary.

---

## NATS Subject Conventions

| Subject | Purpose |
|---------|---------|
| `loom.goals.incoming` | Top-level goals for orchestrators |
| `loom.tasks.incoming` | Router picks up tasks here |
| `loom.tasks.{worker_type}.{tier}` | Routed tasks; workers subscribe with queue groups |
| `loom.tasks.dead_letter` | Unroutable or rate-limited tasks |
| `loom.results.{goal_id}` | Results flow back to orchestrators |

---

## Design Rules

**Workers are stateless.** They process one task and reset (via `reset()` hook).
No state carries between tasks — this is enforced, not optional.

**All inter-actor communication uses typed Pydantic messages.** `TaskMessage`,
`TaskResult`, `OrchestratorGoal`, `CheckpointState` in `core/messages.py`.

**The router is deterministic.** It does not use an LLM. It routes by
`worker_type` and `model_tier` using rules in `configs/router_rules.yaml`.
Unroutable tasks go to `loom.tasks.dead_letter`.

**Workers have strict I/O contracts.** Validated by `core/contracts.py`. Input
and output schemas are defined per-worker in their YAML config. Boolean values
are correctly distinguished from integers.

**Three model tiers exist:** `local` (Ollama), `standard` (Claude Sonnet etc.),
`frontier` (Claude Opus etc.). The router and task metadata decide which tier
handles each task.

**Rate limiting:** Token-bucket rate limiter enforces per-tier dispatch throttling
based on `rate_limits` in `router_rules.yaml`.

---

## Component Details

### LLM Worker (`worker/runner.py`)

The core worker lifecycle:

1. Receive `TaskMessage` from NATS queue
2. Validate input against worker's `input_schema`
3. Resolve file references from workspace (if configured)
4. Inject knowledge sources into system prompt
5. Call LLM backend with system prompt + user message
6. If tools are configured, run multi-turn tool execution loop (max 10 rounds)
7. Parse and validate output against worker's `output_schema`
8. Publish `TaskResult` to results subject
9. Reset worker state

Features: resilient JSON parsing (strips markdown fences, handles preamble),
knowledge silo loading and write-back, file-ref resolution via WorkspaceManager.

### Processor Worker (`worker/processor.py`)

Non-LLM backend support for CPU-bound or deterministic tasks. Implements
`ProcessingBackend` ABC (async) and `SyncProcessingBackend` (sync, run in
thread pool). Provides `BackendError` hierarchy for structured error handling.

### Orchestrator (`orchestrator/runner.py`)

Full decompose → dispatch → collect → synthesize loop:

- **GoalDecomposer:** LLM-based task decomposition grounded in a worker manifest
- **ResultSynthesizer:** Deterministic merge + optional LLM synthesis modes
- **CheckpointManager:** Pluggable store (in-memory for testing, Redis for production), configurable TTL

### Pipeline Orchestrator (`orchestrator/pipeline.py`)

Sequential stage execution where each stage maps inputs from previous stage
outputs. Supports conditions, timeouts, and input mapping expressions.

### Router (`router/router.py`)

Deterministic task dispatch with:
- Worker type → tier resolution from `router_rules.yaml`
- Token-bucket rate limiting per tier
- Dead-letter routing for unroutable/rate-limited tasks

### Message Bus (`bus/`)

Abstracted behind `MessageBus` ABC:
- `InMemoryBus` for unit testing (no infrastructure)
- `NATSBus` for production
- `BaseActor` accepts `bus=` kwarg for injection

### Contrib Packages

- **DuckDB** (`contrib/duckdb/`): `DuckDBViewTool` (view-based LLM tool),
  `DuckDBVectorTool` (semantic similarity search), `DuckDBQueryBackend`
  (FTS, filtering, stats, vector search)
- **Redis** (`contrib/redis/`): `RedisCheckpointStore` for production checkpoint persistence
- **RAG** (`contrib/rag/`): Telegram ingestion, text normalization, chunking,
  vector storage, LLM analysis actors

---

## Worker Configuration

Workers are configured via YAML files in `configs/workers/`. Each config defines:

```yaml
name: summarizer
kind: llm              # or "processor"
default_tier: local    # local | standard | frontier
system_prompt: |
  You are a text summarizer...
input_schema:
  type: object
  properties:
    text: { type: string }
  required: [text]
output_schema:
  type: object
  properties:
    summary: { type: string }
  required: [summary]
```

Copy `configs/workers/_template.yaml` to create new workers. See
[Building Workflows](building-workflows.md) for a comprehensive guide.

---

*For setup instructions, see [Getting Started](GETTING_STARTED.md).
For Kubernetes deployment, see [Kubernetes](KUBERNETES.md).*
