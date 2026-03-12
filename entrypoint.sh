#!/bin/bash
# Worker container entrypoint.
# Launches the Loom worker CLI with config from environment variables.
#
# Required env vars:
#   WORKER_CONFIG  — Path to worker config YAML (e.g., configs/workers/summarizer.yaml)
#   MODEL_TIER     — Tier this worker serves (local, standard, frontier)
#   NATS_URL       — NATS server URL (e.g., nats://nats:4222)
#
# Optional env vars (used by the worker at runtime, not by this script):
#   OLLAMA_URL       — Ollama server URL (for local tier)
#   ANTHROPIC_API_KEY — Anthropic API key (for standard/frontier tiers)
#   FRONTIER_MODEL    — Override frontier model name
exec python -m loom.cli.main worker \
    --config "$WORKER_CONFIG" \
    --tier "$MODEL_TIER" \
    --nats-url "$NATS_URL"
