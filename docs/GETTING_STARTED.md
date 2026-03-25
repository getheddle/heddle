# Getting Started

**Loom — Lightweight Orchestrated Operational Mesh**

New to Loom? Start with [Concepts](CONCEPTS.md) to understand the mental model.

---

## Quick Start (No Infrastructure Needed)

The fastest way to use Loom — analyze Telegram channels in 5 commands:

```bash
# 1. Install
uv sync --extra rag

# 2. Configure (interactive wizard — detects Ollama, prompts for API keys)
uv run loom setup

# 3. Ingest Telegram exports
uv run loom rag ingest /path/to/telegram/exports/*.json

# 4. Search
uv run loom rag search "earthquake damage reports"

# 5. Open the dashboard
uv run loom rag serve
```

The `loom setup` wizard detects Ollama, prompts for API keys, and writes
`~/.loom/config.yaml`. All settings can be overridden via environment
variables or CLI flags. See [Configuration](CONFIG.md) for details.

## Build Your First Worker

Once you've tried the RAG pipeline, build your own AI step — or use one of
the six that ship with Loom:

| Worker | What it does | Tier |
|--------|-------------|------|
| `summarizer` | Compress text into structured summary with key points | local |
| `classifier` | Assign text to categories with confidence | local |
| `extractor` | Pull structured fields from unstructured text | standard |
| `translator` | Translate between languages with auto-detection | local |
| `qa` | Answer questions from provided context with citations | local |
| `reviewer` | Review content quality against configurable criteria | standard |

See [Workers Reference](workers-reference.md) for full I/O schemas and examples.

```bash
# Create your own worker interactively
uv run loom new worker

# Or chain shipped workers into a pipeline
uv run loom new pipeline

# Validate configs (no infrastructure needed)
uv run loom validate configs/workers/*.yaml

# Test in the web UI
uv run loom workshop
```

No NATS or infrastructure needed. The Workshop calls LLM backends directly.

> **That's it for basic usage.** Everything below is for when you need the
> full distributed infrastructure (multi-user, scaling, custom workers).

---

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- At least one LLM backend (Ollama recommended to start)
- NATS and Valkey for full infrastructure (not needed for Quick Start)

---

## 1. Install Python Dependencies

```bash
# Requires uv (https://docs.astral.sh/uv/)
uv sync --all-extras
```

Loom has optional extras for integrations:

```bash
uv sync --extra rag           # RAG pipeline (DuckDB + Ollama embeddings)
uv sync --extra lancedb       # LanceDB vector store (ANN search, alternative to DuckDB)
uv sync --extra telegram      # Live Telegram channel capture via Telethon
uv sync --extra duckdb        # DuckDB tools and query backends
uv sync --extra redis         # Redis/Valkey-backed checkpoint store
uv sync --extra local         # Ollama client for local models
uv sync --extra workshop      # Worker Workshop web UI (FastAPI, Jinja2, DuckDB)
uv sync --extra mcp           # MCP gateway (Model Context Protocol)
uv sync --extra otel          # OpenTelemetry distributed tracing
uv sync --extra tui           # Terminal dashboard (Textual)
uv sync --extra mdns          # mDNS/Bonjour service discovery on LAN
uv sync --extra scheduler     # Cron expression parsing (croniter)
uv sync --extra eval          # DeepEval LLM output quality evaluation
uv sync --extra docs          # MkDocs-Material API documentation generation
```

---

## 2. Configure LLM Backends

The easiest path — run the setup wizard:

```bash
uv run loom setup
```

This auto-detects Ollama, prompts for API keys, and writes `~/.loom/config.yaml`.

**Or configure manually** via environment variables:

```bash
# Option A: Ollama (free, local, recommended to start)
brew install ollama
ollama serve &
ollama pull llama3.2:3b
export OLLAMA_URL=http://localhost:11434

# Option B: Anthropic API
export ANTHROPIC_API_KEY=sk-ant-...

# Option C: Any OpenAI-compatible API (vLLM, LiteLLM, llama.cpp server)
# See OpenAICompatibleBackend in src/loom/worker/backends.py
```

Settings resolution priority: CLI flags > environment variables > `~/.loom/config.yaml` > built-in defaults. See [Configuration](CONFIG.md) for the full reference.

---

## 3. Run the Unit Tests (No Infrastructure Needed)

```bash
uv run pytest tests/ -v -m "not integration and not deepeval"
```

This runs all unit tests without needing NATS or Valkey.

---

## 4. Set Up Infrastructure (NATS + Valkey)

> **Skip this** if you only need the RAG pipeline or Workshop.
> The steps below are for the full distributed actor mesh.

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
# Option 1: TUI dashboard (recommended)
uv sync --extra tui
uv run loom ui --nats-url nats://localhost:4222

# Option 2: NATS CLI (raw messages)
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
uv run loom worker --config configs/workers/my_worker.yaml --tier local
```

Or test it without NATS using the Workshop:

```bash
uv run loom workshop --port 8080
# Open http://localhost:8080 → Workers → my_worker → Test
```

---

## What's Next

| Goal | Guide |
|------|-------|
| Understand the mental model | [Concepts](CONCEPTS.md) |
| Build workers, pipelines, tools | [Building Workflows](building-workflows.md) |
| Set up RAG analysis pipeline | [RAG How-To](rag-howto.md) |
| Configure settings and API keys | [Configuration](CONFIG.md) |
| Full CLI command reference | [CLI Reference](CLI_REFERENCE.md) |
| Test and evaluate workers | [Workshop](workshop.md) |
| Deploy to production | [Local Deployment](LOCAL_DEPLOYMENT.md) / [Kubernetes](KUBERNETES.md) |
| Debug issues | [Troubleshooting](TROUBLESHOOTING.md) |
| Understand design decisions | [Design Invariants](DESIGN_INVARIANTS.md) |

---

*For architecture details, see [Architecture](ARCHITECTURE.md).
For the full CLI reference, see [CLI Reference](CLI_REFERENCE.md).*
