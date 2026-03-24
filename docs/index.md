# Loom

**Actor-based multi-LLM orchestration framework** for building resilient, observable AI workflows.

## Overview

Loom provides a production-ready framework for orchestrating multiple LLM calls through
an actor-based architecture built on NATS messaging, with built-in support for
checkpointing, tool use, and OpenTelemetry tracing with GenAI semantic conventions.

## Quick Start

```bash
pip install loom  # or: uv add loom
```

See [Getting Started](GETTING_STARTED.md) for full setup instructions.

## Key Features

- **Actor-based architecture** — Isolated, message-driven components on NATS
- **Multi-LLM orchestration** — Decompose → Dispatch → Collect → Synthesize
- **Pipeline stages** — Chain multiple processing steps with data flow
- **Tool use** — Automatic tool-call loops with configurable depth
- **Checkpointing** — Resume interrupted workflows from Valkey state
- **OpenTelemetry** — Distributed tracing with GenAI semantic conventions
- **MCP integration** — Model Context Protocol server and bridge
- **Workshop** — Interactive evaluation and tuning UI

## Architecture

```text
┌──────────────┐     ┌──────────────┐     ┌─────────────┐
│ Orchestrator │────▶│  NATS Bus    │────▶│   Workers   │
│  (decompose) │◀────│  (messages)  │◀────│  (LLM call) │
└──────────────┘     └──────────────┘     └─────────────┘
       │                                        │
       ▼                                        ▼
┌─────────────┐                           ┌─────────────┐
│   Valkey    │                           │   Ollama /  │
│ (checkpoint)│                           │  Anthropic  │
└─────────────┘                           └─────────────┘
```
