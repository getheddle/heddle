#!/bin/bash
exec python -m loom.cli.main worker \
    --config "$WORKER_CONFIG" \
    --tier "$MODEL_TIER" \
    --nats-url "$NATS_URL"
