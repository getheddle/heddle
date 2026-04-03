# Heddle

**Turn what you know into testable AI steps. Chain them into workflows.
Measure whether they work. Scale when ready.**

---

## What Heddle Does

Most AI tools give you one big prompt and one model. That works until it
doesn't — the prompt gets unwieldy, you can't test parts independently,
and asking the same model to review its own work doesn't catch real
problems.

Heddle splits AI work into focused **steps**. Each step has a clear job, a
typed contract (so you know what goes in and what comes out), and can use
a different model. You test steps individually, chain them into pipelines,
and measure whether changes help or hurt.

```text
  Document ──► Extract ──► Classify ──► Summarize ──► Report
                 │            │            │
                 │            │            └─ Claude Opus (complex reasoning)
                 │            └─ Ollama local (fast, free)
                 └─ Ollama local (fast, free)
```

Steps can run in parallel, use different AI models, and be tested with the
built-in Workshop web UI — all without deploying any infrastructure.

## Quick Start

```bash
pip install heddle-ai[workshop]    # install from PyPI
heddle setup                       # configure (auto-detects Ollama)
heddle workshop                    # open the web UI at localhost:8080
```

Open your browser, pick a worker (summarizer, classifier, extractor, qa,
reviewer, or translator), paste some text, and see results. No data files
needed — just text you already have.

Want to analyze Telegram channels? See the [RAG quickstart](GETTING_STARTED.md#rag-quickstart).

## Who This Is For

**Anyone hitting the limits of single-prompt AI.** Start with the six
shipped workers in Workshop — no coding needed.

**Researchers and analysts** — process documents, extract data, build
analytical pipelines with knowledge silos and blind audit review.

**AI engineers** — multi-step LLM workflows with typed contracts,
tool-use, and pipeline orchestration.

**Platform teams** — Kubernetes deployment with rate limiting, model tier
management, and OpenTelemetry tracing.

## Key Features

| Feature | What It Does |
|---------|-------------|
| **6 Ready-Made Workers** | Summarizer, classifier, extractor, translator, QA, reviewer — use immediately |
| **Workshop** | Web UI for testing, evaluating, and comparing step outputs |
| **Built-in Evaluation** | Test suites, scoring, golden dataset baselines, regression detection |
| **Config-Driven** | Define workers in YAML — no Python code needed for LLM steps |
| **Knowledge Silos** | Per-worker access control; blind audit workers can't see what they're reviewing |
| **Pipeline Orchestration** | Chain steps with automatic dependency detection and parallelism |
| **Three Model Tiers** | Local (Ollama), Standard (Claude Sonnet), Frontier (Claude Opus) |
| **RAG Pipeline** | Telegram channel ingestion, chunking, vector search |
| **MCP Gateway** | Expose any workflow as an MCP server |

## Documentation

Start here:

| Guide | Description |
|-------|-------------|
| **[Concepts](CONCEPTS.md)** | How Heddle works — the mental model in plain language |
| **[Getting Started](GETTING_STARTED.md)** | Install, configure, and get your first result |
| **[Why Heddle?](WHY_HEDDLE.md)** | How Heddle compares to other frameworks — and when not to use it |
| **[Workshop Tour](WORKSHOP_TOUR.md)** | What each Workshop screen does and when to use it |
| **[Workers Reference](workers-reference.md)** | 6 shipped workers with I/O schemas and examples |
| **[CLI Reference](CLI_REFERENCE.md)** | All commands with every flag and default |

Go deeper:

| Guide | Description |
|-------|-------------|
| [Building Workflows](building-workflows.md) | Custom steps, pipelines, tools, knowledge |
| [RAG Pipeline](rag-howto.md) | Social media stream analysis end-to-end |
| [Architecture](ARCHITECTURE.md) | System design, message flow, NATS subjects |
| [Deployment](LOCAL_DEPLOYMENT.md) | Local, Docker, and [Kubernetes](KUBERNETES.md) |
