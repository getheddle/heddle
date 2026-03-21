# Loom — Lightweight Orchestrated Operational Mesh

[![CI](https://github.com/IranTransitionProject/loom/actions/workflows/ci.yml/badge.svg)](https://github.com/IranTransitionProject/loom/actions/workflows/ci.yml)
[![codecov](https://codecov.io/github/IranTransitionProject/loom/graph/badge.svg?token=4N0F5XBZW9)](https://codecov.io/github/IranTransitionProject/loom)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-brightgreen.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
<!-- Keep in sync with pyproject.toml version -->
[![Loom v0.8.0](https://img.shields.io/badge/loom-v0.8.0-blueviolet.svg)](https://github.com/IranTransitionProject/loom)
[![Status: Active Development](https://img.shields.io/badge/status-active_development-brightgreen.svg)]()

**Actor-based Python framework for orchestrating multi-LLM AI workflows via NATS messaging.**

---

## Why This Project Exists

A single monolithic LLM conversation breaks down when you need to work with
large databases, complex knowledge graphs, or tasks that require multiple model
tiers working together. Context windows fill up, prompts become unwieldy, and
there is no clean way to split cognitive work across specialized agents.

Loom solves this by decomposing AI work across narrowly-scoped stateless worker
actors coordinated by an orchestrator through a message bus. Each worker has a
single system prompt, strict I/O contracts, and resets after every task. The
orchestrator decomposes goals, routes subtasks, and synthesizes results —
checkpointing its own context when it gets too large.

The result is an AI workflow system that scales with complexity instead of
collapsing under it.

---

## What This Project Provides

**Stateless LLM Workers** — each worker has a single system prompt and strict
JSON Schema I/O contracts. Workers call LLM backends (Anthropic, Ollama, or
any OpenAI-compatible API), support multi-turn tool-use, knowledge injection,
and file-ref resolution. They reset after every task.

**Processing Workers** — non-LLM backends for CPU-bound or deterministic tasks.
Implement the `ProcessingBackend` ABC and plug into the same messaging
infrastructure.

**Goal Decomposition and Synthesis** — an LLM-driven orchestrator breaks
complex goals into subtasks, dispatches them to appropriate workers, collects
results, and synthesizes final answers. Self-checkpointing to Redis prevents
context overflow.

**Pipeline Orchestration** — dependency-aware parallel stage execution with
automatic parallelism, conditional stages, and concurrent goal processing.

**Deterministic Routing** — a pure-logic router dispatches tasks by worker type
and model tier with token-bucket rate limiting and dead-letter handling. No LLM
in the routing path.

**Scheduled Dispatch** — a time-driven actor dispatches goals or tasks on cron
expressions or fixed intervals, configured entirely in YAML.

**MCP Gateway** — any LOOM system becomes a Model Context Protocol server with a
single YAML config. Workers, pipelines, and query backends are automatically
discovered as MCP tools with typed input schemas. Supports stdio and
streamable-http transports.

**Worker Workshop** — a web-based tool for defining, testing, evaluating, and
deploying LLM workers. Interactive test bench, eval suite runner with scoring,
pipeline stage editor, and worker version tracking. No NATS needed for testing.

**Contrib Ecosystem** — optional packages for DuckDB (analytics, vector search),
Redis (checkpoint persistence), and RAG (ingestion, chunking, embedding, analysis).

---

## Who This Is For

**AI/ML engineers** building multi-agent systems who need worker isolation,
typed messaging, and structured orchestration instead of ad-hoc prompt chaining.

**Platform teams** deploying AI infrastructure who need rate limiting, model tier
management, dead-letter handling, and Kubernetes-ready containerization.

**Researchers and experimenters** who want to prototype multi-LLM workflows
quickly using YAML worker configs and a local Ollama backend.

**Anyone** who has outgrown single-prompt LLM applications and needs a framework
that separates concerns across specialized actors.

---

## Current State

| Component | Status |
|-----------|--------|
| Core (messages, contracts, config, workspace) | Complete |
| LLM Worker (Anthropic, Ollama, OpenAI-compatible) | Complete |
| Processing Worker (sync/async backends) | Complete |
| Tool-use (multi-turn, dynamic loading) | Complete |
| Knowledge sources and silos | Complete |
| Orchestrator (decompose/dispatch/synthesize) | Complete |
| Pipeline orchestrator (sequential stages) | Complete |
| Router (deterministic, rate-limited) | Complete |
| Checkpoint (Redis + in-memory) | Complete |
| Scheduler (cron + interval dispatch) | Complete |
| MCP gateway (config-driven tool server) | Complete |
| Contrib: DuckDB, Redis, RAG | Complete |
| Worker Workshop (web UI) | Complete |
| Unit tests | 1472 passing, 90% coverage |

---

## Quick Start

```bash
# Requires Python 3.11+ and uv (https://docs.astral.sh/uv/)
uv sync --all-extras

# Run unit tests (no infrastructure needed)
uv run pytest tests/ -v -m "not integration"

# Lint
uv run ruff check src/ tests/
```

For the full 7-step setup with infrastructure and LLM backends, see
[Getting Started](docs/GETTING_STARTED.md).

---

## Documentation

- **[Architecture](docs/ARCHITECTURE.md)** — Source tree, message flow, NATS
  subjects, design rules, component details
- **[Getting Started](docs/GETTING_STARTED.md)** — Installation, infrastructure
  setup, LLM backend configuration, running your first workflow
- **[Building Workflows](docs/building-workflows.md)** — Comprehensive guide:
  workers, pipelines, knowledge, file-refs, routing, silos, tools, embeddings,
  DuckDB, MCP gateway
- **[Worker Workshop](docs/workshop.md)** — Workshop web app architecture,
  component reference, data model, enhancement guide
- **[RAG Pipeline](docs/rag-howto.md)** — Social media stream ingestion,
  chunking, vector storage, and analysis
- **[Kubernetes Deployment](docs/KUBERNETES.md)** — Minikube manifests,
  container builds, environment variables
- **[Coding Guide](docs/CODING_GUIDE.md)** — Coding, documentation, and commenting standards for contributors
- **[Contributing](docs/CONTRIBUTING.md)** — CLA, technical standards, PR process

---

## Get Involved

**Use the framework.** Build workers for your domain, create pipelines,
experiment with orchestration patterns. Copy `configs/workers/_template.yaml`
to get started.

**Contribute.** New worker types, contrib packages, test coverage, and
documentation improvements are all welcome.
See [Contributing](docs/CONTRIBUTING.md).

**Report issues.** Bug reports with reproducible steps help the most.

---

## AI-Assisted Development

This project uses Claude (Anthropic) as a development and maintenance tool.
The [`CLAUDE.md`](CLAUDE.md) file documents the project's architecture, design
rules, and current state for AI-assisted sessions.

AI-generated code is subject to the same standards as human contributions:
typed messages, stateless workers, validated I/O contracts, and test coverage.

---

## License

[MPL 2.0](LICENSE) — Mozilla Public License 2.0. Modified source files must
remain open; unmodified files can be combined with proprietary code in a
Larger Work.

Alternative licensing available for organizations with copyleft constraints.
Contact: <hooman@mac.com>

---

*For governance, succession, and contributor rights, see [GOVERNANCE.md](GOVERNANCE.md).*
