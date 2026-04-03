# Configuration

## Overview

Heddle stores user defaults in `~/.heddle/config.yaml`. This file is created
automatically by `heddle setup` or can be written by hand. Every setting in it
can be overridden at runtime via environment variables or CLI flags.

## Priority Chain

When Heddle resolves a setting, the first source that provides a value wins:

```text
CLI flags  >  environment variables  >  ~/.heddle/config.yaml  >  built-in defaults
```

**Example:** if `config.yaml` sets `ollama_url: "http://host1:11434"` and the
environment has `OLLAMA_URL=http://host2:11434`, the environment variable wins.
Passing `--ollama-url http://host3:11434` on the command line overrides both.

## Config File Format

```yaml
backends:
  ollama_url: "http://localhost:11434"
  ollama_model: "llama3.2:3b"
  anthropic_api_key: "sk-ant-..."
  embedding_model: "nomic-embed-text"
  frontier_model: "claude-opus-4-20250514"

rag:
  rag_data_dir: "/path/to/exports"
  rag_vector_store: "duckdb"    # or "lancedb"
  rag_db_path: "~/.heddle/rag.duckdb"

workshop:
  workshop_port: 8080
```

All sections and keys are optional. Heddle falls back to sensible built-in
defaults for anything omitted.

## Environment Variables

Only four config fields have environment-variable mappings:

| Config Field       | Environment Variable | Used By            |
|--------------------|----------------------|--------------------|
| `ollama_url`       | `OLLAMA_URL`         | All LLM commands   |
| `ollama_model`     | `OLLAMA_MODEL`       | Worker, Workshop   |
| `anthropic_api_key`| `ANTHROPIC_API_KEY`  | Worker, Workshop   |
| `frontier_model`   | `FRONTIER_MODEL`     | Worker, Workshop   |

Other settings (`rag_*`, `workshop_*`, `embedding_model`) are config-file or
CLI-flag only.

## Creating the Config

**Interactive wizard** (recommended for first-time setup):

```bash
heddle setup
```

Walks through backends, RAG paths, and Workshop port with sensible defaults.

**Non-interactive** (CI / automation):

```bash
heddle setup --non-interactive
```

Writes a config with all built-in defaults. Combine with env vars to
customize:

```bash
OLLAMA_URL=http://gpu-box:11434 heddle setup --non-interactive
```

**Manual creation** -- just write the YAML file directly:

```bash
mkdir -p ~/.heddle
cat > ~/.heddle/config.yaml << 'EOF'
backends:
  ollama_url: "http://localhost:11434"
  ollama_model: "command-r7b:latest"
EOF
chmod 600 ~/.heddle/config.yaml
```

## Security

- File permissions are set to `0o600` (owner read/write only) by `heddle setup`.
  Enforce this manually if you create the file by hand.
- API keys are stored in **plaintext**. On shared machines, prefer setting
  `ANTHROPIC_API_KEY` as an environment variable instead.
- Never commit `config.yaml` to version control. The project `.gitignore`
  already excludes `~/.heddle/`.

## The ~/.heddle Directory

Everything Heddle persists locally lives under `~/.heddle/`:

| Path                  | Purpose                                      |
|-----------------------|----------------------------------------------|
| `config.yaml`         | User configuration (this document)           |
| `workshop.duckdb`     | Workshop evaluation and version data         |
| `rag.duckdb`          | RAG vector store (default path)              |
| `apps/`               | Deployed app bundles                         |
| `sessions/`           | Session markers (MCP session lifecycle)      |

## Programmatic Access

```python
from heddle.cli.config import (
    load_config,
    resolve_config,
    apply_config_to_env,
    HeddleConfig,
)

# Load ~/.heddle/config.yaml (returns HeddleConfig dataclass)
config = load_config()

# Merge CLI overrides with env vars and config file
config = resolve_config(cli_overrides={"ollama_url": "http://custom:11434"})

# Push resolved values into os.environ for backwards compatibility
apply_config_to_env(config)
```

`resolve_config` applies the full priority chain (CLI > env > file > defaults)
and returns a single `HeddleConfig` with every field populated.
