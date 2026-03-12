# CLAUDE.md — Loom project context

## What this project is

Loom (Lightweight Orchestrated Operational Mesh) is an actor-based framework for orchestrating multiple LLM agents via NATS messaging. It was built to replace a monolithic AI conversation approach that breaks down as database volume and knowledge graph complexity grow.

The core idea: instead of one big LLM context, split work across narrowly-scoped stateless workers coordinated by an orchestrator through a message bus.

## Project structure

```
src/loom/
  core/         # Message schemas (Pydantic), base actor class, I/O contract validation, config loader
  worker/       # Stateless LLM worker actor, LLM backend adapters (Anthropic/Ollama/OpenAI-compat), knowledge loader
  orchestrator/ # Orchestrator actor, checkpoint system (Redis), goal decomposer, result synthesizer, pipeline orchestrator
  router/       # Deterministic task router with dead-letter handling and rate limiting (not an LLM — pure logic)
  bus/          # NATS message bus adapter
  cli/          # Click CLI entry point (worker, processor, pipeline, orchestrator, router, submit commands)
configs/
  workers/      # YAML configs defining each worker's system prompt, I/O schema, default tier
  orchestrators/# Orchestrator configs
  router_rules.yaml  # Tier overrides and rate limits (enforced by token-bucket limiter)
k8s/            # Kubernetes manifests (Minikube-ready, Kustomize)
tests/          # Unit tests (messages, contracts, checkpoint, pipeline, workers, processor) and integration test
```

## Key design rules

- **Workers are stateless.** They process one task and reset (via `reset()` hook). No state carries between tasks — this is enforced, not optional.
- **All inter-actor communication uses typed Pydantic messages** (`TaskMessage`, `TaskResult`, `OrchestratorGoal`, `CheckpointState` in `core/messages.py`).
- **The router is deterministic** — it does not use an LLM. It routes by `worker_type` and `model_tier` using rules in `configs/router_rules.yaml`. Unroutable tasks go to `loom.tasks.dead_letter`.
- **Workers have strict I/O contracts** validated by `core/contracts.py`. Input and output schemas are defined per-worker in their YAML config. Boolean values are correctly distinguished from integers.
- **Three model tiers exist:** `local` (Ollama), `standard` (Claude Sonnet etc.), `frontier` (Claude Opus etc.). The router and task metadata decide which tier handles each task.
- **Rate limiting:** Token-bucket rate limiter enforces per-tier dispatch throttling based on `rate_limits` in `router_rules.yaml`.
- **NATS subject convention:**
  - `loom.tasks.incoming` — Router picks up tasks here
  - `loom.tasks.{worker_type}.{tier}` — Routed tasks land here; workers subscribe with queue groups
  - `loom.tasks.dead_letter` — Unroutable/rate-limited tasks land here
  - `loom.results.{goal_id}` — Results flow back to orchestrators
  - `loom.goals.incoming` — Top-level goals for orchestrators

## Build and test commands

```bash
# Create venv and install (Python 3.11+ required)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run unit tests (no infrastructure needed — excludes integration tests)
pytest tests/ -v -m "not integration"

# Run ALL tests including integration (needs NATS + workers running)
pytest tests/ -v

# Lint
ruff check src/

# Run a worker locally (needs NATS running)
loom worker --config configs/workers/summarizer.yaml --tier local --nats-url nats://localhost:4222

# Run the router
loom router --nats-url nats://localhost:4222

# Run the orchestrator
loom orchestrator --config configs/orchestrators/default.yaml --nats-url nats://localhost:4222

# Run a pipeline
loom pipeline --config configs/orchestrators/doc_pipeline.yaml --nats-url nats://localhost:4222

# Submit a test goal
loom submit "some goal text" --nats-url nats://localhost:4222
```

## Current state

All major components are implemented and functional:

- **Core:** Message schemas, contract validation (with correct bool/int handling), base actor (with signal handling and configurable concurrency), config loader (with schema validation).
- **Worker:** LLMWorker with resilient JSON parsing (strips markdown fences, handles preamble), `reset()` hook after each task, knowledge source loader with logging. Backends updated to current Anthropic API version (2024-10-22).
- **Router:** Deterministic routing with dead-letter subject for unroutable tasks, token-bucket rate limiting per tier.
- **Orchestrator:** Full OrchestratorActor with decompose/dispatch/collect/synthesize loop. GoalDecomposer (LLM-based task decomposition), ResultSynthesizer (merge + LLM synthesis modes), CheckpointManager (Redis-backed, configurable TTL).
- **PipelineOrchestrator:** Fully functional sequential stage execution with input mapping, conditions, timeouts.
- **ProcessorWorker:** Non-LLM backend support, tested with DoclingBackend.
- **CLI:** All 6 commands registered (worker, processor, pipeline, orchestrator, router, submit). Tier mismatch warnings on worker startup.
- **Tests:** 75+ unit tests pass (messages, contracts, checkpoint, pipeline, workers, processor). Integration test has `@pytest.mark.integration` marker and polling-based result collection.
- **Infrastructure:** Dockerfiles and k8s manifests updated with correct CMDs and no stale FIXMEs.

## Known issues

- **Knowledge sources:** Module exists (`worker/knowledge.py`) but is not wired into the worker startup path. The loader works but `LLMWorker.process()` doesn't call it yet.
- **Summarizer file_ref gap:** LLMWorker doesn't resolve file_refs from workspace. Workers that need file content require custom logic or inline data in the payload.

## What to implement next

1. **Wire knowledge sources** — call `load_knowledge_sources()` in LLMWorker.process()
2. **File-ref resolution** — add workspace file reading to LLMWorker for stages that need extracted content
3. **Orchestrator tests** — unit tests for OrchestratorActor (decompose/dispatch/synthesize loop)
4. **End-to-end integration test** — full goal submission through router/workers/orchestrator
5. **Router dead-letter consumer** — implement a dead-letter processor for monitoring/retry

## What NOT to do

- Don't add shared mutable state between workers. Workers are isolated actors.
- Don't put LLM logic in the router. It's deterministic routing only.
- Don't merge worker configs into a single monolithic prompt. Each worker stays narrow.
- Don't skip I/O contract validation — it's the only safety net between actors.
- Workers must always output valid JSON matching their output_schema. The system prompt enforces this.
