# Getting Started

**Loom — Lightweight Orchestrated Operational Mesh**

---

## Prerequisites

- Python 3.11+
- At least one LLM backend (Ollama recommended to start)
- NATS and Redis for full infrastructure (not needed for unit tests)

---

## 1. Install Python Dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Loom has optional extras for integrations:

```bash
pip install loom[duckdb]      # DuckDB tools and query backends
pip install loom[redis]       # Redis-backed checkpoint store
pip install loom[local]       # Ollama client
pip install loom[rag]         # RAG pipeline (DuckDB + Ollama)
pip install loom[scheduler]   # Cron expression parsing (croniter)
pip install loom[mcp]         # MCP gateway (Model Context Protocol SDK)
```

---

## 2. Run the Unit Tests (No Infrastructure Needed)

```bash
pytest tests/ -v -m "not integration"
```

This runs all unit tests (messages, contracts, checkpoint, pipeline, workers,
processor, tools, tool-use, knowledge silos, embeddings, contrib/duckdb) without
needing NATS or Redis. The integration test is excluded by marker.

---

## 3. Set Up Infrastructure (NATS + Redis)

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

---

## 4. Connect an LLM Backend

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

---

## 5. Start the Router, Orchestrator, and a Worker

```bash
# Terminal 1: Start the router
loom router --nats-url nats://localhost:4222

# Terminal 2: Start the orchestrator
loom orchestrator --config configs/orchestrators/default.yaml --nats-url nats://localhost:4222

# Terminal 3: Start a summarizer worker
loom worker --config configs/workers/summarizer.yaml --tier local --nats-url nats://localhost:4222
```

---

## 6. Submit a Test Task

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

---

## 7. Create Your Own Worker

```bash
cp configs/workers/_template.yaml configs/workers/my_worker.yaml
```

Edit the file — define a system prompt, input/output schemas, and default tier.
Then start it:

```bash
loom worker --config configs/workers/my_worker.yaml --tier local
```

For a comprehensive guide to building workers, pipelines, knowledge injection,
tool-use, and more, see [Building Workflows](building-workflows.md).

---

## CLI Reference

```bash
# Run a worker locally
loom worker --config configs/workers/summarizer.yaml --tier local --nats-url nats://localhost:4222

# Run a processor worker
loom processor --config configs/workers/my_processor.yaml --nats-url nats://localhost:4222

# Run the router
loom router --nats-url nats://localhost:4222

# Run the orchestrator
loom orchestrator --config configs/orchestrators/default.yaml --nats-url nats://localhost:4222

# Run a pipeline
loom pipeline --config configs/orchestrators/my_pipeline.yaml --nats-url nats://localhost:4222

# Run the scheduler
loom scheduler --config configs/schedulers/example.yaml --nats-url nats://localhost:4222

# Submit a goal
loom submit "some goal text" --nats-url nats://localhost:4222

# Run an MCP server (stdio transport, default)
loom mcp --config configs/mcp/docman.yaml

# Run an MCP server (streamable-http transport)
loom mcp --config configs/mcp/docman.yaml --transport streamable-http --port 8000

# Lint
ruff check src/
```

---

*For architecture details, see [Architecture](ARCHITECTURE.md).
For Kubernetes deployment, see [Kubernetes](KUBERNETES.md).*
