# CLI Reference

All commands are invoked as `loom COMMAND [OPTIONS]`. Commands are grouped by
whether they need a running NATS server.

## Overview

| Command | Purpose | NATS Required |
|---|---|---|
| `loom setup` | Interactive configuration wizard | No |
| `loom rag ingest` | Ingest Telegram exports into vector store | No |
| `loom rag search` | Semantic search | No |
| `loom rag stats` | Vector store statistics | No |
| `loom rag serve` | Workshop with RAG dashboard | No |
| `loom worker` | LLM worker actor | Yes |
| `loom processor` | Non-LLM processor worker | Yes |
| `loom pipeline` | Pipeline orchestrator | Yes |
| `loom orchestrator` | Dynamic LLM orchestrator | Yes |
| `loom scheduler` | Time-driven task scheduler | Yes |
| `loom router` | Deterministic task router | Yes |
| `loom submit` | Submit a goal | Yes |
| `loom mcp` | MCP server gateway | Yes |
| `loom workshop` | Worker Workshop web UI | No |
| `loom ui` | Terminal dashboard (TUI) | Yes |
| `loom mdns` | mDNS service discovery | No |
| `loom dead-letter monitor` | Dead-letter queue consumer | Yes |

---

## Getting Started Commands (no NATS)

### loom setup

Interactive wizard that detects your environment and writes a config file.

```
loom setup [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config-path` | `~/.loom/config.yaml` | Config file path |
| `--non-interactive` | `false` | Skip prompts, use defaults |

Steps performed:

1. Detects Ollama at `localhost:11434`
2. Prompts for Anthropic API key (optional)
3. Checks/pulls the embedding model
4. Scans for Telegram export files
5. Writes `~/.loom/config.yaml`

---

### loom rag (group)

All RAG subcommands share a set of group-level options.

```
loom rag [GROUP-OPTIONS] COMMAND
```

**Group options** (inherited by every subcommand):

| Option | Default | Description |
|---|---|---|
| `--config-path` | `~/.loom/config.yaml` | Config file path |
| `--db-path` | *(from config)* | Override vector store path |
| `--store` | *(from config)* | Backend: `duckdb` or `lancedb` |
| `--ollama-url` | *(from config)* | Override Ollama URL |
| `--embedding-model` | *(from config)* | Override embedding model |

#### loom rag ingest

Ingest Telegram JSON exports into the vector store.

```
loom rag ingest [OPTIONS] PATHS...
```

| Option | Default | Description |
|---|---|---|
| `--embed / --no-embed` | `--embed` | Generate embeddings via Ollama |
| `--window-hours` | `6` | Time window size in hours |
| `--chunk-target` | `400` | Target chunk size in chars |
| `--chunk-max` | `600` | Maximum chunk size in chars |

`PATHS` accepts one or more directories or `result.json` files.

#### loom rag search

Run a semantic similarity search against the vector store.

```
loom rag search [OPTIONS] QUERY
```

| Option | Default | Description |
|---|---|---|
| `--limit`, `-n` | `10` | Max results |
| `--min-score` | `0.0` | Minimum similarity score |

#### loom rag stats

Print vector store statistics (row count, embedding dimensions, disk size).

```
loom rag stats
```

No additional options beyond the group options.

#### loom rag serve

Start the Workshop web UI with the RAG dashboard enabled.

```
loom rag serve [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--port` | `8080` | Workshop port |
| `--host` | `127.0.0.1` | Bind address |

---

## Infrastructure Commands (NATS required)

All infrastructure commands connect to NATS and typically accept `--nats-url`
and `--skip-preflight`. Most also require a `--config` YAML file that describes
the actor.

### loom worker

Start an LLM worker actor.

```
loom worker --config PATH [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config` | *(required)* | Worker config YAML |
| `--nats-url` | `nats://nats:4222` | NATS server URL |
| `--tier` | `standard` | Model tier: `local`, `standard`, `frontier` |
| `--skip-preflight` | `false` | Skip connectivity checks |

### loom processor

Start a non-LLM processor worker (e.g. extractors, validators).

```
loom processor --config PATH [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config` | *(required)* | Processor config YAML |
| `--nats-url` | `nats://nats:4222` | NATS server URL |
| `--tier` | `local` | Model tier |
| `--skip-preflight` | `false` | Skip connectivity checks |

### loom pipeline

Start a pipeline orchestrator that chains workers in sequence.

```
loom pipeline --config PATH [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config` | *(required)* | Pipeline config YAML |
| `--nats-url` | `nats://nats:4222` | NATS server URL |
| `--skip-preflight` | `false` | Skip connectivity checks |

### loom orchestrator

Start the dynamic LLM orchestrator (goal decomposition, delegation).

```
loom orchestrator --config PATH [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config` | *(required)* | Orchestrator config YAML |
| `--nats-url` | `nats://nats:4222` | NATS server URL |
| `--redis-url` | `redis://redis:6379` | Redis URL (state store) |
| `--skip-preflight` | `false` | Skip connectivity checks |

### loom scheduler

Start the time-driven task scheduler.

```
loom scheduler --config PATH [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config` | *(required)* | Scheduler config YAML |
| `--nats-url` | `nats://nats:4222` | NATS server URL |
| `--skip-preflight` | `false` | Skip connectivity checks |

### loom router

Start the deterministic task router.

```
loom router [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config` | `configs/router_rules.yaml` | Router rules YAML |
| `--nats-url` | `nats://nats:4222` | NATS server URL |
| `--skip-preflight` | `false` | Skip connectivity checks |

### loom submit

Submit a goal to the orchestrator for processing.

```
loom submit GOAL [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--nats-url` | `nats://nats:4222` | NATS server URL |
| `--context` | *(none)* | Key=value pairs (repeatable) |

Example:

```bash
loom submit "Process document" --context file_ref=test.pdf --context lang=en
```

---

## UI & Discovery Commands

### loom workshop

Start the Worker Workshop web UI.

```
loom workshop [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--port` | `8080` | HTTP port |
| `--host` | `127.0.0.1` | Bind address |
| `--configs-dir` | `configs/` | Directory of worker configs |
| `--db-path` | `~/.loom/workshop.duckdb` | Workshop database |
| `--nats-url` | *(none)* | Optional NATS URL for live status |
| `--apps-dir` | `~/.loom/apps` | Custom apps directory |

### loom ui

Launch the terminal dashboard (TUI) for monitoring actors in real time.

```
loom ui [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--nats-url` | `nats://localhost:4222` | NATS server URL |

### loom mdns

Broadcast mDNS service records so other Loom nodes can discover this machine.

```
loom mdns [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--workshop-port` | `8080` | Advertised Workshop port |
| `--nats-port` | `4222` | Advertised NATS port |
| `--mcp-port` | `0` | Advertised MCP port (0 = disabled) |
| `--host` | *(auto-detect)* | Hostname to advertise |

### loom mcp

Start the MCP (Model Context Protocol) server gateway.

```
loom mcp --config PATH [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--config` | *(required)* | MCP config YAML |
| `--transport` | `stdio` | Transport: `stdio` or `sse` |
| `--host` | `127.0.0.1` | Bind address (SSE only) |
| `--port` | `8000` | Port (SSE only) |
| `--skip-preflight` | `false` | Skip connectivity checks |

### loom dead-letter monitor

Consume and display messages from the dead-letter queue.

```
loom dead-letter monitor [OPTIONS]
```

| Option | Default | Description |
|---|---|---|
| `--nats-url` | `nats://nats:4222` | NATS server URL |
| `--max-size` | `1000` | Max messages to retain in memory |

---

## Pre-flight Checks

Infrastructure commands (`worker`, `processor`, `pipeline`, `orchestrator`,
`scheduler`, `router`, `mcp`) run three pre-flight checks before starting:

1. **NATS connectivity** -- verifies the NATS server is reachable and the
   JetStream API is available.
2. **Model availability** -- for LLM workers, confirms the configured model is
   loaded in Ollama (or that the API key is set for cloud models).
3. **Stream/subject setup** -- ensures the required NATS streams and subjects
   exist, creating them if necessary.

Pass `--skip-preflight` to bypass all three checks. Useful in CI or when you
know the infrastructure is already running.

---

## Environment Variables

| Variable | Affects | Description |
|---|---|---|
| `OLLAMA_URL` | All commands | Ollama base URL (overrides config) |
| `OLLAMA_MODEL` | `worker`, `processor` | Default model name |
| `ANTHROPIC_API_KEY` | `worker`, `orchestrator` | Anthropic API key for cloud models |
| `FRONTIER_MODEL` | `worker` | Model name for the frontier tier |
| `OPENAI_API_KEY` | `worker` | OpenAI-compatible API key |
| `OPENAI_BASE_URL` | `worker` | OpenAI-compatible base URL |
| `LOOM_TRACE` | All infrastructure | Enable trace logging (`1` / `true`) |
| `LOOM_TRACE_CONTENT` | All infrastructure | Include message payloads in traces |
