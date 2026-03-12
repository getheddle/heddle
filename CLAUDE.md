# CLAUDE.md — Loom project context

## What this project is

Loom (Lightweight Orchestrated Operational Mesh) is an actor-based framework for orchestrating multiple LLM agents via NATS messaging. It was built to replace a monolithic AI conversation approach that breaks down as database volume and knowledge graph complexity grow.

The core idea: instead of one big LLM context, split work across narrowly-scoped stateless workers coordinated by an orchestrator through a message bus.

## Project structure

```
src/loom/
  core/         # Message schemas (Pydantic), base actor class, I/O contract validation, config loader
  worker/       # Stateless LLM worker actor, LLM backend adapters (Anthropic/Ollama/OpenAI-compat), knowledge loader
  orchestrator/ # Orchestrator actor (stub), checkpoint system (Redis), decomposer (stub), synthesizer (stub)
  router/       # Deterministic task router (not an LLM — pure logic routing by worker_type and model_tier)
  bus/          # NATS message bus adapter
  cli/          # Click CLI entry point
configs/
  workers/      # YAML configs defining each worker's system prompt, I/O schema, default tier
  orchestrators/# Orchestrator configs
  router_rules.yaml  # Tier overrides and rate limits
k8s/            # Kubernetes manifests (Minikube-ready, Kustomize)
tests/          # Unit tests (messages, contracts) and integration test stub
```

## Key design rules

- **Workers are stateless.** They process one task and reset. No state carries between tasks — this is enforced, not optional.
- **All inter-actor communication uses typed Pydantic messages** (`TaskMessage`, `TaskResult`, `OrchestratorGoal`, `CheckpointState` in `core/messages.py`).
- **The router is deterministic** — it does not use an LLM. It routes by `worker_type` and `model_tier` using rules in `configs/router_rules.yaml`.
- **Workers have strict I/O contracts** validated by `core/contracts.py`. Input and output schemas are defined per-worker in their YAML config.
- **Three model tiers exist:** `local` (Ollama), `standard` (Claude Sonnet etc.), `frontier` (Claude Opus etc.). The router and task metadata decide which tier handles each task.
- **NATS subject convention:**
  - `loom.tasks.incoming` — Router picks up tasks here
  - `loom.tasks.{worker_type}.{tier}` — Routed tasks land here; workers subscribe with queue groups
  - `loom.results.{goal_id}` — Results flow back to orchestrators
  - `loom.goals.incoming` — Top-level goals for orchestrators

## Build and test commands

```bash
# Create venv and install (Python 3.11+ required)
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# Run unit tests (no infrastructure needed)
pytest tests/test_messages.py tests/test_contracts.py -v

# Lint
ruff check src/

# Run a worker locally (needs NATS running)
loom worker --config configs/workers/summarizer.yaml --tier local --nats-url nats://localhost:4222

# Run the router
loom router --nats-url nats://localhost:4222

# Submit a test goal
loom submit "some goal text" --nats-url nats://localhost:4222
```

## Current state

The scaffolding is complete and wired:
- Message schemas, contract validation, base actor, LLM backends, worker runtime, router, NATS adapter, CLI — all implemented and working.
- **PipelineOrchestrator** is fully functional (sequential stage execution with input mapping, conditions, timeouts).
- **ProcessorWorker** is implemented and working (non-LLM backend support, tested with DoclingBackend).
- **49 unit tests pass** (messages, contracts, pipeline, workers, processor).
- **1 integration test exists** but requires running infrastructure (NATS + workers).
- Orchestrator has a stub `handle_message` — the decompose/dispatch/synthesize loop is the next thing to build.
- `orchestrator/decomposer.py` and `orchestrator/synthesizer.py` are empty stubs with detailed TODO guidance.
- `orchestrator/checkpoint.py` is fully implemented (Redis-backed context compression with tiktoken token counting).

## Known issues (FIXME)

- **Router CLI bug:** `cli/main.py` router command exits immediately after subscribing — `asyncio.get_event_loop().run_forever()` is unreachable after `asyncio.run()`. Fix documented in code.
- **Dockerfile.orchestrator:** CMD references nonexistent `loom orchestrator` CLI command. OrchestratorActor is a stub.
- **Anthropic API version:** backends.py uses old `anthropic-version: 2023-06-01`.
- **LLMWorker JSON parsing:** `runner.py` uses `json.loads()` directly on LLM output — fails if model wraps response in markdown fences or adds surrounding text.
- **Deprecated asyncio calls:** Several files use `asyncio.get_event_loop()` instead of `asyncio.get_running_loop()`.
- **Router rate limits:** Defined in `router_rules.yaml` but not enforced by the router.
- **Knowledge sources:** Module exists (`worker/knowledge.py`) but is not wired into the worker startup path.

## What to implement next

1. **Fix router CLI bug** — the asyncio.run()/run_forever() issue (see FIXME in cli/main.py)
2. **LLMWorker JSON parsing resilience** — strip markdown fences, handle non-JSON preamble
3. **OrchestratorActor** — implement the decompose/dispatch/synthesize loop using decomposer.py and synthesizer.py
4. **Wire knowledge sources** — call `load_knowledge_sources()` in LLMWorker.process()
5. **Add `orchestrator` CLI command** — register OrchestratorActor in cli/main.py, fix Dockerfile.orchestrator
6. **Enforce rate limits** — implement rate limiting in TaskRouter based on router_rules.yaml
7. **Expand test coverage** — checkpoint tests, orchestrator tests, integration test with pytest marker

## What NOT to do

- Don't add shared mutable state between workers. Workers are isolated actors.
- Don't put LLM logic in the router. It's deterministic routing only.
- Don't merge worker configs into a single monolithic prompt. Each worker stays narrow.
- Don't skip I/O contract validation — it's the only safety net between actors.
- Workers must always output valid JSON matching their output_schema. The system prompt enforces this.
