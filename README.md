# Loom

[![CI](https://github.com/IranTransitionProject/loom/actions/workflows/ci.yml/badge.svg)](https://github.com/IranTransitionProject/loom/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://irantransitionproject.github.io/loom/)
[![codecov](https://codecov.io/github/IranTransitionProject/loom/graph/badge.svg?token=4N0F5XBZW9)](https://codecov.io/github/IranTransitionProject/loom)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-brightgreen.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
<!-- Keep in sync with pyproject.toml version -->
[![Loom v0.8.0](https://img.shields.io/badge/loom-v0.8.0-blueviolet.svg)](https://github.com/IranTransitionProject/loom)
[![Status: Active Development](https://img.shields.io/badge/status-active_development-brightgreen.svg)]()

**Split complex AI work into focused steps. Test them individually. Chain them into workflows. Scale when you need to.**

---

## Try It in 60 Seconds

```bash
pip install uv                                       # if you don't have uv
git clone https://github.com/IranTransitionProject/loom.git && cd loom
uv sync --extra rag                                   # install RAG pipeline
uv run loom setup                                     # configure (auto-detects Ollama)
uv run loom rag ingest /path/to/telegram/exports/*.json
uv run loom rag search "earthquake damage reports"
uv run loom rag serve                                 # open dashboard at localhost:8080
```

No servers to run. No configuration files to write. The setup wizard handles everything.

---

## What Loom Does

Instead of one giant AI prompt that tries to do everything, Loom lets you break
work into small, focused **steps** — each with a clear job, testable
independently, and using the right model for the task.

```text
  Document ──► Extract ──► Classify ──► Summarize ──► Report
                 │            │            │
                 │            │            └─ Claude Opus (complex reasoning)
                 │            └─ Ollama local (fast, free)
                 └─ Ollama local (fast, free)
```

Steps can run in parallel, use different AI models, and be tested with the
built-in Workshop web UI — all without deploying any infrastructure.

When you're ready to scale, Loom adds a message bus (NATS) that connects
everything for production use.

---

## Who This Is For

**Researchers and analysts** — analyze social media streams, extract data from
documents, build knowledge graphs. Start with `loom rag` and the Workshop
dashboard. No infrastructure knowledge needed.

**AI engineers** — build multi-step LLM workflows with typed contracts, tool-use,
knowledge injection, and pipeline orchestration. Test everything locally before
deploying.

**Platform teams** — deploy to Kubernetes with rate limiting, model tier
management, dead-letter handling, and OpenTelemetry tracing. Scale any component
independently.

---

## Three Ways to Use Loom

### 1. Command line (no setup)

Ingest data, search, and analyze — all from the terminal:

```bash
uv run loom rag ingest exports/*.json    # ingest Telegram channels
uv run loom rag search "protest reports"  # semantic search
uv run loom rag stats                     # store statistics
```

### 2. Build your own steps (guided)

Scaffold workers and pipelines interactively — YAML is generated for you:

```bash
uv run loom new worker                   # create a step from prompts
uv run loom new pipeline                 # chain steps into a workflow
uv run loom validate configs/workers/*.yaml  # check your configs
uv run loom workshop --port 8080         # test and evaluate in the web UI
```

Six ready-made workers ship with Loom: **summarizer**, **classifier**,
**extractor**, **translator**, **qa** (question answering with source
citations), and **reviewer** (quality review against configurable criteria).

### 3. Distributed infrastructure (production)

For teams, continuous processing, or high-throughput scenarios:

```bash
uv run loom router --nats-url nats://localhost:4222
uv run loom worker --config configs/workers/summarizer.yaml --tier local
uv run loom pipeline --config configs/orchestrators/my_pipeline.yaml
uv run loom submit "Analyze the quarterly reports"
```

Scale any component by running more copies — NATS load-balances automatically.

---

## Key Features

| Feature | What It Does |
|---------|-------------|
| **6 Ready-Made Workers** | Summarizer, classifier, extractor, translator, QA, reviewer — chain them immediately |
| **LLM Steps** | YAML-defined AI tasks with system prompts, JSON Schema contracts, tool-use |
| **Processor Steps** | Non-LLM tasks (PDF extraction, chunking, embedding) in the same pipeline |
| **Document Processing** | PDF/DOCX extraction via MarkItDown (fast) or Docling (deep OCR). Smart fallback. |
| **Pipeline Orchestration** | Chain steps with automatic dependency detection and parallelism |
| **Three Model Tiers** | Local (Ollama), Standard (Claude Sonnet), Frontier (Claude Opus) |
| **Workshop** | Web UI for testing, evaluating, and comparing step outputs |
| **RAG Pipeline** | Telegram channel ingestion, chunking, vector search (DuckDB or LanceDB) |
| **MCP Gateway** | Expose any workflow as an MCP server with a single YAML config |
| **Config Wizard** | `loom setup` auto-detects backends; `loom new` scaffolds workers/pipelines |
| **Config Validation** | `loom validate` checks configs without starting infrastructure |
| **Live Monitoring** | TUI dashboard, OpenTelemetry tracing, dead-letter inspection |
| **Deployment** | Docker Compose, Kubernetes manifests, mDNS discovery |

---

## Documentation

Start here:

| Guide | Description |
|-------|-------------|
| **[Concepts](docs/CONCEPTS.md)** | How Loom works — the mental model in plain language |
| **[Getting Started](docs/GETTING_STARTED.md)** | Install and run your first pipeline |
| **[Configuration](docs/CONFIG.md)** | `~/.loom/config.yaml` reference and priority chain |
| **[CLI Reference](docs/CLI_REFERENCE.md)** | All 19 commands with every flag and default |
| **[Workers Reference](docs/workers-reference.md)** | 6 shipped workers with I/O schemas and examples |

Go deeper:

| Guide | Description |
|-------|-------------|
| [RAG Pipeline](docs/rag-howto.md) | Social media stream analysis end-to-end |
| [Building Workflows](docs/building-workflows.md) | Custom steps, pipelines, tools, knowledge |
| [Workshop](docs/workshop.md) | Web UI architecture and enhancement guide |
| [Architecture](docs/ARCHITECTURE.md) | System design, message flow, NATS subjects |
| [Design Invariants](docs/DESIGN_INVARIANTS.md) | Non-obvious design decisions (read before structural changes) |
| [Troubleshooting](docs/TROUBLESHOOTING.md) | Common issues and solutions |
| [Deployment](docs/LOCAL_DEPLOYMENT.md) | Local, Docker, and [Kubernetes](docs/KUBERNETES.md) |

---

## Current State

| Area | Status | Details |
|------|--------|---------|
| Core framework | Complete | Messages, contracts, config, workspace |
| LLM backends | Complete | Anthropic, Ollama, OpenAI-compatible |
| Workers & processors | Complete | Tool-use, knowledge silos, embeddings |
| Orchestration | Complete | Goal decomposition, pipelines, scheduling |
| RAG pipeline | Complete | Ingest, chunk, embed, search (DuckDB + LanceDB) |
| Workshop web UI | Complete | Test bench, eval runner, pipeline editor |
| MCP gateway | Complete | FastMCP 3.x, session tools, workshop tools |
| Tests | 1643 passing | 90% coverage, no infrastructure needed |

---

## Get Involved

**Use it.** Start with `uv run loom setup` and go from there.

**Contribute.** New step types, contrib packages, test coverage, and docs are
welcome. See [Contributing](docs/CONTRIBUTING.md).

**Report issues.** Bug reports with reproducible steps help the most.

---

## AI-Assisted Development

This project uses Claude (Anthropic) as a development tool.
[`CLAUDE.md`](CLAUDE.md) documents the architecture and design rules for
AI-assisted sessions. AI-generated code meets the same standards as human
contributions: typed messages, stateless workers, validated contracts, tests.

---

## License

[MPL 2.0](LICENSE) — Modified source files must remain open; unmodified files
can be combined with proprietary code. Alternative licensing available for
organizations with copyleft constraints.
Contact: <admin@irantransitionproject.org>

*For governance, succession, and contributor rights, see [GOVERNANCE.md](GOVERNANCE.md).*
