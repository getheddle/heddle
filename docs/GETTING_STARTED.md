# Getting Started

**Loom — Lightweight Orchestrated Operational Mesh**

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- At least one LLM backend (Ollama recommended to start)
- NATS and Valkey for full infrastructure (not needed for unit tests)

---

## 1. Install Python Dependencies

```bash
# Requires uv (https://docs.astral.sh/uv/)
uv sync --all-extras
```

Loom has optional extras for integrations:

```bash
uv sync --extra duckdb        # DuckDB tools and query backends
uv sync --extra redis         # Redis-backed checkpoint store
uv sync --extra local         # Ollama client
uv sync --extra rag           # RAG pipeline (DuckDB + Ollama)
uv sync --extra scheduler     # Cron expression parsing (croniter)
uv sync --extra mcp           # MCP gateway (Model Context Protocol SDK)
uv sync --extra workshop      # Worker Workshop web UI (FastAPI, Jinja2, DuckDB)
uv sync --extra otel          # OpenTelemetry distributed tracing
```

See [Architecture — Distributed Tracing](ARCHITECTURE.md#distributed-tracing-tracing) for
GenAI semantic conventions and environment variables (`LOOM_TRACE_CONTENT`).

```bash
uv sync --extra tui           # Terminal dashboard (Textual)
uv sync --extra mdns          # mDNS/Bonjour service discovery on LAN
uv sync --extra eval          # DeepEval LLM output quality evaluation (uses Ollama judge)
uv sync --extra docs          # Sphinx API documentation generation
```

---

## 2. Run the Unit Tests (No Infrastructure Needed)

```bash
uv run pytest tests/ -v -m "not integration"
```

This runs all unit tests (messages, contracts, checkpoint, pipeline, workers,
processor, tools, tool-use, knowledge silos, embeddings, contrib/duckdb) without
needing NATS or Valkey. The integration test is excluded by marker.

---

## 3. Set Up Infrastructure (NATS + Valkey)

The simplest path — run NATS and Valkey locally:

```bash
# Install via Homebrew (Mac) or use Docker
brew install nats-server valkey

# Start them
nats-server &
valkey-server &
```

Or with Docker:

```bash
docker run -d --name nats -p 4222:4222 nats:2.10-alpine
docker run -d --name valkey -p 6379:6379 valkey/valkey:8-alpine
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
uv run loom router --nats-url nats://localhost:4222

# Terminal 2: Start the orchestrator
uv run loom orchestrator --config configs/orchestrators/default.yaml --nats-url nats://localhost:4222

# Terminal 3: Start a summarizer worker
uv run loom worker --config configs/workers/summarizer.yaml --tier local --nats-url nats://localhost:4222
```

---

## 6. Submit a Test Task

```bash
# Terminal 4: Send a task through the system
uv run loom submit "Summarize the main points of the UN Charter preamble" --nats-url nats://localhost:4222
```

Monitor what's happening:

```bash
# Option 1: Use the built-in TUI dashboard (recommended)
uv sync --extra tui
uv run loom ui --nats-url nats://localhost:4222

# Option 2: Use the NATS CLI to watch raw messages
brew tap nats-io/nats-tools && brew install nats-io/nats-tools/nats
nats sub "loom.>" --server=nats://localhost:4222
```

The TUI dashboard shows live goals, tasks, pipeline stages, and a scrolling
event log in your terminal. See [Architecture — TUI Dashboard](ARCHITECTURE.md#tui-dashboard-tui)
for details.

---

## 7. Create Your Own Worker

```bash
cp configs/workers/_template.yaml configs/workers/my_worker.yaml
```

Edit the file — define a system prompt, input/output schemas, and default tier.
Then start it:

```bash
uv run loom worker --config configs/workers/my_worker.yaml --tier local
```

For a comprehensive guide to building workers, pipelines, knowledge injection,
tool-use, and more, see [Building Workflows](building-workflows.md).

---

## CLI Reference

```bash
# Run a worker locally
uv run loom worker --config configs/workers/summarizer.yaml --tier local --nats-url nats://localhost:4222

# Run a processor worker
uv run loom processor --config configs/workers/my_processor.yaml --nats-url nats://localhost:4222

# Run the router
uv run loom router --nats-url nats://localhost:4222

# Run the orchestrator
uv run loom orchestrator --config configs/orchestrators/default.yaml --nats-url nats://localhost:4222

# Run a pipeline
uv run loom pipeline --config configs/orchestrators/my_pipeline.yaml --nats-url nats://localhost:4222

# Run the scheduler
uv run loom scheduler --config configs/schedulers/example.yaml --nats-url nats://localhost:4222

# Submit a goal
uv run loom submit "some goal text" --nats-url nats://localhost:4222

# Run an MCP server (stdio transport, default)
uv run loom mcp --config configs/mcp/docman.yaml

# Run an MCP server (streamable-http transport)
uv run loom mcp --config configs/mcp/docman.yaml --transport streamable-http --port 8000

# Run the Worker Workshop web UI
uv run loom workshop --port 8080

# Launch the real-time TUI dashboard
uv run loom ui --nats-url nats://localhost:4222

# Monitor the dead-letter queue
uv run loom dead-letter monitor --nats-url nats://localhost:4222

# Advertise services on LAN via mDNS/Bonjour
uv run loom mdns --workshop-port 8080 --nats-port 4222

# Lint
uv run ruff check src/
```

---

*For architecture details, see [Architecture](ARCHITECTURE.md).
For Kubernetes deployment, see [Kubernetes](KUBERNETES.md).*
