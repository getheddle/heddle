# Loom

**Encode your professional judgment into testable, composable AI steps.
Chain them into workflows. Measure whether they work. Scale when ready.**

---

## What Loom Does

The bottleneck with AI isn't the model — it's the **input layer**. Every
frontier model already knows your domain. What it doesn't know is your
process: the judgment calls, the edge cases, the analytical sequence that
makes your work yours.

Loom gives you infrastructure to encode that judgment into focused AI
**steps**, each defined in YAML with a system prompt, typed contracts,
and knowledge access rules. Test them. Chain them into pipelines. Measure
whether they work. Scale when ready.

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
pip install loom-ai[workshop]    # install from PyPI
loom setup                       # configure (auto-detects Ollama)
loom workshop                    # open the web UI at localhost:8080
```

Open your browser, pick a worker (summarizer, classifier, extractor, qa,
reviewer, or translator), paste some text, and see results. No data files
needed — just text you already have.

Want to analyze Telegram channels? See the [RAG quickstart](GETTING_STARTED.md#rag-quickstart).

## Who This Is For

**Domain experts** — analysts, researchers, policy professionals. Define
workers in YAML, test in the Workshop, iterate until the output matches
your judgment. No Python needed.

**AI engineers** — build multi-step LLM workflows with typed contracts,
tool-use, knowledge injection, and pipeline orchestration. Test everything
locally before deploying.

**Platform teams** — deploy to Kubernetes with rate limiting, model tier
management, dead-letter handling, and OpenTelemetry tracing. Scale any
component independently.

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
| **[Concepts](CONCEPTS.md)** | How Loom works — the mental model in plain language |
| **[Getting Started](GETTING_STARTED.md)** | Install, configure, and get your first result |
| **[Why Loom?](WHY_LOOM.md)** | How Loom compares to other frameworks — and when not to use it |
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
