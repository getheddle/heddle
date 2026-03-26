# Loom

[![CI](https://github.com/IranTransitionProject/loom/actions/workflows/ci.yml/badge.svg)](https://github.com/IranTransitionProject/loom/actions/workflows/ci.yml)
[![Docs](https://img.shields.io/badge/docs-GitHub%20Pages-blue)](https://irantransitionproject.github.io/loom/)
[![codecov](https://codecov.io/github/IranTransitionProject/loom/graph/badge.svg?token=4N0F5XBZW9)](https://codecov.io/github/IranTransitionProject/loom)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![License: MPL 2.0](https://img.shields.io/badge/License-MPL_2.0-brightgreen.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
<!-- Keep in sync with pyproject.toml version -->
[![Loom v0.9.0](https://img.shields.io/badge/loom-v0.9.0-blueviolet.svg)](https://github.com/IranTransitionProject/loom)
[![Status: Active Development](https://img.shields.io/badge/status-active_development-brightgreen.svg)]()

**Encode your professional judgment into testable, composable AI steps.
Chain them into workflows. Measure whether they work. Scale when ready.**

---

## Try It in 60 Seconds

```bash
pip install loom-ai[workshop]                         # install from PyPI
loom setup                                            # configure (auto-detects Ollama)
loom workshop                                         # open web UI at localhost:8080
```

Open your browser → pick a worker (summarizer, classifier, extractor) →
paste any text → click Run. No data files needed.

**Have Telegram exports?** Install with `pip install loom-ai[rag]` instead,
then run `loom rag ingest`, `loom rag search`, and `loom rag serve` for
full social media stream analysis.

Or from source:

```bash
git clone https://github.com/IranTransitionProject/loom.git && cd loom
uv sync --extra workshop
uv run loom setup
```

No servers to run. No configuration files to write. The setup wizard handles everything.

---

## The Problem Loom Solves

The bottleneck with AI isn't the model — it's the **input layer**. Every
frontier model already knows your domain. What it doesn't know is your
process: the sequence of judgment calls you make when working through a
problem, the edge cases you check, what matters and what's noise.

Most AI tools optimize the output layer — fine-tuning, wrappers, retrieval.
Loom goes the other direction. It gives you infrastructure to encode your
judgment into **worker configs** (YAML files with system prompts, typed
contracts, and knowledge access rules), **test them** against evaluation
suites, **track versions** so you know whether a change helped, and
**chain them** into multi-step pipelines where each step uses the right
model for the task.

```text
  Document ──► Extract ──► Classify ──► Summarize ──► Report
                 │            │            │
                 │            │            └─ Claude Opus (complex reasoning)
                 │            └─ Ollama local (fast, free)
                 └─ Ollama local (fast, free)
```

Steps run in parallel when they can, use different AI models, and are
tested with the built-in Workshop web UI — all without deploying any
infrastructure. When you're ready to scale, Loom adds a message bus (NATS)
that connects everything for production use.

> **[Why Loom?](docs/WHY_LOOM.md)** — How Loom compares to LangChain,
> CrewAI, AutoGen, and vertical AI wrappers. When to use it and when not to.

---

## Who This Is For

**Domain experts** — analysts, researchers, policy professionals, anyone
whose work involves structured reasoning over complex material. You
define workers in YAML (no Python needed), test them in the Workshop
browser UI, and iterate until the output matches your judgment. Your
expertise is the input. Loom makes it testable and composable.

**AI engineers** — build multi-step LLM workflows with typed contracts,
tool-use, knowledge injection, and pipeline orchestration. Test everything
locally before deploying.

**Platform teams** — deploy to Kubernetes with rate limiting, model tier
management, dead-letter handling, and OpenTelemetry tracing. Scale any
component independently.

---

## Three Ways to Use Loom

### 1. Workshop (no setup beyond install)

Test shipped workers in the browser — paste text, get results:

```bash
loom workshop                            # open web UI
# → Workers → summarizer → Test → paste text → Run
```

Six ready-made workers ship with Loom: **summarizer**, **classifier**,
**extractor**, **translator**, **qa** (question answering with source
citations), and **reviewer** (quality review against configurable criteria).

### 2. Build your own steps (guided)

Scaffold workers and pipelines interactively — YAML is generated for you:

```bash
loom new worker                   # create a step from prompts
loom new pipeline                 # chain steps into a workflow
loom validate configs/workers/*.yaml  # check your configs
loom workshop                     # test and evaluate in the web UI
```

### 3. Distributed infrastructure (production)

For teams, continuous processing, or high-throughput scenarios:

```bash
loom router --nats-url nats://localhost:4222
loom worker --config configs/workers/summarizer.yaml --tier local
loom pipeline --config configs/orchestrators/my_pipeline.yaml
loom submit "Analyze the quarterly reports"
```

Scale any component by running more copies — NATS load-balances automatically.

---

## Key Features

| Feature | What It Does |
|---------|-------------|
| **6 Ready-Made Workers** | Summarizer, classifier, extractor, translator, QA, reviewer — chain them immediately |
| **Workshop** | Web UI for testing, evaluating, and comparing step outputs — the compounding flywheel |
| **Built-in Evaluation** | Test suites, scoring, golden dataset baselines, regression detection |
| **Config-Driven** | Define workers in YAML — no Python code needed for LLM steps |
| **Knowledge Silos** | Per-worker access control; blind audit workers can't see what they're reviewing |
| **Pipeline Orchestration** | Chain steps with automatic dependency detection and parallelism |
| **Three Model Tiers** | Local (Ollama), Standard (Claude Sonnet), Frontier (Claude Opus) |
| **Document Processing** | PDF/DOCX extraction via MarkItDown (fast) or Docling (deep OCR) |
| **RAG Pipeline** | Telegram channel ingestion, chunking, vector search (DuckDB or LanceDB) |
| **MCP Gateway** | Expose any workflow as an MCP server with a single YAML config |
| **Config Wizard** | `loom setup` auto-detects backends; `loom new` scaffolds workers/pipelines |
| **Live Monitoring** | TUI dashboard, OpenTelemetry tracing, dead-letter inspection |
| **Deployment** | Docker Compose, Kubernetes manifests, mDNS discovery |

---

## Documentation

Start here:

| Guide | Description |
|-------|-------------|
| **[Concepts](docs/CONCEPTS.md)** | How Loom works — the mental model in plain language |
| **[Getting Started](docs/GETTING_STARTED.md)** | Install and get your first result |
| **[Why Loom?](docs/WHY_LOOM.md)** | How Loom compares to other frameworks — and when not to use it |
| **[Workshop Tour](docs/WORKSHOP_TOUR.md)** | What each Workshop screen does and when to use it |
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

**Use it.** Start with `loom setup` and go from there.

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
