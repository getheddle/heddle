# LOOM — Lightweight Orchestrated Operational Mesh

Loom is a Python framework for building AI workflows where a single monolithic LLM conversation breaks down — large databases, complex knowledge graphs, tasks that need multiple model tiers working together.

Instead of one big prompt, Loom splits work across **narrowly-scoped worker actors** coordinated by an **orchestrator** through a message bus. Each worker has a single system prompt, strict I/O contracts, and resets after every task. The orchestrator decomposes goals, routes subtasks, and synthesizes results — checkpointing its own context when it gets too large.

**Status:** All major components implemented and tested. 223 unit tests pass. See `docs/building-workflows.md` for a guide to building your own AI workflows with Loom.

## What's here

```
src/loom/
├── core/
│   ├── messages.py      # Pydantic schemas: TaskMessage, TaskResult, OrchestratorGoal, CheckpointState
│   ├── actor.py          # Base actor class (NATS subscribe/publish lifecycle)
│   ├── contracts.py      # Lightweight JSON Schema validation for worker I/O
│   ├── workspace.py      # File-ref resolution with path traversal protection
│   └── config.py         # YAML config loader
├── worker/
│   ├── runner.py         # LLM worker: validate → resolve files → inject knowledge → call LLM → tool loop → validate → publish
│   ├── processor.py      # Non-LLM worker: ProcessingBackend, SyncProcessingBackend, BackendError
│   ├── backends.py       # LLM adapters: Anthropic, Ollama, OpenAI-compatible (with tool-use support)
│   ├── tools.py          # ToolProvider ABC, SyncToolProvider, dynamic tool loader
│   ├── knowledge.py      # Knowledge sources + knowledge silos (folder read/write, tool injection)
│   └── embeddings.py     # EmbeddingProvider ABC, OllamaEmbeddingProvider (/api/embed)
├── orchestrator/
│   ├── runner.py         # Orchestrator actor: decompose → dispatch → collect → synthesize
│   ├── pipeline.py       # Pipeline orchestrator: sequential stage execution with input mapping
│   ├── checkpoint.py     # Self-summarization: compresses orchestrator context to Redis snapshots
│   ├── decomposer.py     # LLM-driven goal → subtask decomposition with worker manifest grounding
│   └── synthesizer.py    # Multi-result aggregation (deterministic merge + LLM synthesis modes)
├── router/
│   └── router.py         # Deterministic task routing with dead-letter handling and rate limiting
├── bus/
│   └── nats_adapter.py   # NATS pub/sub/request wrapper
├── cli/
│   └── main.py           # Click CLI: worker, processor, pipeline, orchestrator, router, submit
└── contrib/
    └── duckdb/            # DuckDB tools and backends (optional: pip install loom[duckdb])

configs/
├── workers/
│   ├── _template.yaml    # Copy this to create new workers
│   ├── summarizer.yaml   # Text → structured summary (local tier)
│   ├── classifier.yaml   # Text → category with confidence (local tier)
│   └── extractor.yaml    # Text → structured fields (standard tier)
├── orchestrators/
│   └── default.yaml      # General-purpose orchestrator config
└── router_rules.yaml     # Tier overrides and rate limits

docs/
└── building-workflows.md # Getting started guide for building AI workflows

k8s/                      # Kubernetes manifests (Minikube-ready)
Dockerfile.{worker,router,orchestrator}
```

## How the pieces connect

1. **You submit a goal** via CLI or publish to `loom.goals.incoming`
2. **The orchestrator** decomposes it into subtasks (via LLM-driven GoalDecomposer), each targeting a `worker_type`
3. **The router** picks up tasks from `loom.tasks.incoming`, resolves the model tier, enforces rate limits, and publishes to `loom.tasks.{worker_type}.{tier}` (unroutable tasks go to `loom.tasks.dead_letter`)
4. **Workers** (competing consumers via NATS queue groups) pick up tasks, call the appropriate LLM backend, validate the output, and publish results to `loom.results.{goal_id}`
5. **The orchestrator** collects results, decides if more subtasks are needed, and eventually produces a final answer

Workers are stateless — they reset after every task. The orchestrator is longer-lived but checkpoints itself to Redis when its context grows too large, compressing history into a structured summary.

## Getting started

### 1. Install Python dependencies

```bash
# Requires Python 3.11+
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Loom has optional extras for integrations:

```bash
pip install loom[duckdb]   # DuckDB tools and query backends
```

### 2. Run the unit tests (no infrastructure needed)

```bash
pytest tests/ -v -m "not integration"
```

This runs all unit tests (messages, contracts, checkpoint, pipeline, workers, processor, tools, tool-use, knowledge silos, embeddings, contrib/duckdb) without needing NATS or Redis. The integration test is excluded by marker.

### 3. Set up infrastructure (NATS + Redis)

The simplest path — run NATS and Redis locally:

```bash
# Install via Homebrew (Mac) or use Docker
brew install nats-server redis

# Start them
nats-server &
redis-server &
```

Or with Docker:

```bash
docker run -d --name nats -p 4222:4222 nats:2.10-alpine
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

### 4. Connect an LLM backend

Loom supports three backend types. You need at least one.

**Option A: Ollama (free, local, recommended to start)**

```bash
brew install ollama
ollama serve &
ollama pull llama3.2:3b
export OLLAMA_URL=http://localhost:11434
```

**Option B: Anthropic API**

```bash
export ANTHROPIC_API_KEY=sk-ant-...
```

**Option C: Any OpenAI-compatible API** (vLLM, LiteLLM, llama.cpp server, etc.)

Configure via the `OpenAICompatibleBackend` in `src/loom/worker/backends.py`.

### 5. Start the router, orchestrator, and a worker

```bash
# Terminal 1: Start the router
loom router --nats-url nats://localhost:4222

# Terminal 2: Start the orchestrator
loom orchestrator --config configs/orchestrators/default.yaml --nats-url nats://localhost:4222

# Terminal 3: Start a summarizer worker
loom worker --config configs/workers/summarizer.yaml --tier local --nats-url nats://localhost:4222
```

### 6. Submit a test task

```bash
# Terminal 4: Send a task through the system
loom submit "Summarize the main points of the UN Charter preamble" --nats-url nats://localhost:4222
```

Monitor what's happening:

```bash
# Install NATS CLI to watch all messages
brew tap nats-io/nats-tools && brew install nats-io/nats-tools/nats
nats sub "loom.>" --server=nats://localhost:4222
```

### 7. Create your own worker

```bash
cp configs/workers/_template.yaml configs/workers/my_worker.yaml
```

Edit the file — define a system prompt, input/output schemas, and default tier. Then start it:

```bash
loom worker --config configs/workers/my_worker.yaml --tier local
```

## Kubernetes deployment

For running the full mesh on Minikube:

```bash
minikube start --cpus=4 --memory=8192 --driver=docker
eval $(minikube docker-env)

# Build images inside Minikube's Docker
docker build -f Dockerfile.worker -t loom-worker:latest .
docker build -f Dockerfile.router -t loom-router:latest .
docker build -f Dockerfile.orchestrator -t loom-orchestrator:latest .

# Create namespace and API key secret
kubectl create namespace loom
kubectl create secret generic loom-secrets \
  --namespace loom \
  --from-literal=anthropic-api-key="$ANTHROPIC_API_KEY"

# Deploy
kubectl apply -k k8s/
kubectl get pods -n loom -w
```

For Ollama on Mac with Minikube, run Ollama natively on the host and point workers to `http://host.minikube.internal:11434`.

## What to build next

The core framework is functional. Key extension points:

1. **New worker configs** — Add workers specific to your domain (e.g., entity resolver, relationship mapper, evidence grader). See `docs/building-workflows.md` for a walkthrough.
2. **New contrib packages** — Add optional integrations (like `loom.contrib.duckdb`) for databases, search engines, or other backends your workers need.
3. **Dead-letter consumer** — Implement a monitoring/retry service for tasks landing on `loom.tasks.dead_letter`
4. **Orchestrator tests** — Unit tests for the decompose/dispatch/collect/synthesize loop
5. **End-to-end integration test** — Full goal submission through router/workers/orchestrator
