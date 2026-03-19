# Worker Workshop — Design & Architecture

**Web-based tool for the LLM worker lifecycle: Define → Test → Evaluate → Compare → Deploy.**

---

## Overview

The Workshop is a FastAPI web application that lets you build, test, evaluate,
and deploy LLM workers without touching the NATS actor mesh.  It calls LLM
backends directly, validates I/O contracts, scores outputs against test suites,
tracks worker config versions in DuckDB, and edits pipeline stages with
dependency validation.

The key design constraint: **no NATS required**.  The test bench and eval runner
bypass the bus, router, and actor lifecycle entirely — they call
`execute_with_tools()` on the LLM backend directly and validate the result
against the worker's I/O contracts.  This makes the Workshop usable as a
standalone development tool even when no infrastructure is running.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  FastAPI Application (app.py)               │
│                                                             │
│   Jinja2 Templates + HTMX          Static Files (Pico CSS) │
│   ┌────────────────────┐            ┌────────────────────┐  │
│   │ workers/list        │            │ workshop.css       │  │
│   │ workers/detail      │            └────────────────────┘  │
│   │ workers/test        │                                    │
│   │ workers/eval        │                                    │
│   │ workers/eval_detail │                                    │
│   │ pipelines/list      │                                    │
│   │ pipelines/editor    │                                    │
│   │ partials/test_result│                                    │
│   └────────────────────┘                                    │
├─────────────────────────────────────────────────────────────┤
│                    Backend Components                       │
│                                                             │
│  ┌────────────────┐  ┌──────────────┐  ┌────────────────┐  │
│  │ WorkerTestRunner│  │ EvalRunner   │  │ ConfigManager  │  │
│  │ (test_runner.py)│  │(eval_runner) │  │(config_manager)│  │
│  └───────┬────────┘  └──────┬───────┘  └────────┬───────┘  │
│          │                  │                    │          │
│          │                  │          ┌─────────┴───────┐  │
│          │                  │          │ PipelineEditor  │  │
│          │                  │          │(pipeline_editor)│  │
│          │                  │          └─────────────────┘  │
│          │                  │                               │
│  ┌───────▼──────────────────▼────────┐                     │
│  │           WorkshopDB (db.py)      │                     │
│  │   worker_versions │ eval_runs     │                     │
│  │   eval_results    │ worker_metrics│                     │
│  └───────────────────────────────────┘                     │
├─────────────────────────────────────────────────────────────┤
│                    Loom Core (reused)                       │
│                                                             │
│  LLMBackend (backends.py)        validate_input/output()   │
│  execute_with_tools()            validate_worker_config()   │
│  _extract_json()                 validate_pipeline_config() │
│  _load_tool_providers()          load_config()              │
│  build_backends_from_env()       PipelineOrchestrator.*     │
│  load_knowledge_silos()          WorkspaceManager           │
└─────────────────────────────────────────────────────────────┘
```

### Dependency flow

```
app.py
 ├── WorkerTestRunner(backends)      # needs LLM backends
 ├── EvalRunner(test_runner, db)     # wraps runner + persistence
 ├── ConfigManager(configs_dir, db)  # filesystem + version tracking
 └── PipelineEditor                  # stateless, no constructor
```

`create_app()` is the composition root.  It creates all components, wires them
together, and defines all routes as closures that capture the shared instances.

---

## Source files

```
src/loom/workshop/
├── __init__.py           # Package docstring only
├── app.py                # FastAPI app factory (create_app), all route handlers
├── test_runner.py        # WorkerTestRunner — single-payload LLM execution
├── eval_runner.py        # EvalRunner — batch test suite with scoring
├── config_manager.py     # ConfigManager — CRUD for YAML configs
├── pipeline_editor.py    # PipelineEditor — stateless pipeline manipulation
├── db.py                 # WorkshopDB — DuckDB storage
├── templates/
│   ├── base.html         # Layout: nav, Pico CSS, HTMX script
│   ├── workers/
│   │   ├── list.html     # Worker table with Test/Eval action buttons
│   │   ├── detail.html   # YAML editor, clone form, version history
│   │   ├── test.html     # Interactive test bench (HTMX form)
│   │   ├── eval.html     # Eval suite form + past runs table
│   │   └── eval_detail.html  # Per-case results with expandable details
│   ├── pipelines/
│   │   ├── list.html     # Pipeline table
│   │   └── editor.html   # Dependency graph + stage operation forms
│   └── partials/
│       └── test_result.html  # HTMX fragment: test bench result card
└── static/
    └── workshop.css      # Pico CSS overrides + pipeline graph styles
```

---

## Component reference

### WorkerTestRunner (`test_runner.py`)

Executes a worker config against a single payload.  Replicates the full
`LLMWorker.process()` flow without the actor lifecycle:

1. Validate worker config via `validate_worker_config()`
2. Validate input payload against `input_schema` via `validate_input()`
3. Build system prompt:
   - Inject knowledge silos (`load_knowledge_silos()`)
   - Inject legacy knowledge sources (`load_knowledge_sources()`)
   - Resolve file-ref fields via `WorkspaceManager`
4. Load tool providers from silos (`_load_tool_providers()`)
5. Resolve tier → backend (from `build_backends_from_env()` result)
6. Call `execute_with_tools()` — the standalone tool-use loop
7. Parse JSON from raw LLM response via `_extract_json()`
8. Validate output against `output_schema` via `validate_output()`

Returns a `WorkerTestResult` dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `output` | `dict \| None` | Parsed JSON output |
| `raw_response` | `str \| None` | Raw LLM text |
| `validation_errors` | `list[str]` | Output schema violations |
| `input_validation_errors` | `list[str]` | Input schema violations |
| `token_usage` | `dict[str, int]` | `prompt_tokens`, `completion_tokens` |
| `latency_ms` | `int` | Wall-clock time |
| `model_used` | `str \| None` | Model identifier from backend |
| `error` | `str \| None` | Exception message if failed |
| `success` | `bool` (property) | True if no errors and valid output |

**Key design decisions:**
- Calls `execute_with_tools()` directly — this is a module-level function
  extracted from `LLMWorker` specifically for Workshop reuse.
- Catches all exceptions and returns them in `error` — never raises.
- Knowledge silo injection failures are logged but don't abort the test.

### EvalRunner (`eval_runner.py`)

Runs a list of test cases against a worker config with scoring.

**Inputs:**
- `config`: Worker config dict (same as YAML)
- `test_suite`: List of `{"name": str, "input": dict, "expected_output": dict}`
- `tier`: Model tier override
- `scoring`: `"field_match"` or `"exact_match"`
- `max_concurrency`: Semaphore bound (default 3)

**Execution:**
1. Save worker config version to DB (deduplicates by SHA-256 hash)
2. Create eval run record in DB
3. Run all test cases concurrently (bounded by `asyncio.Semaphore`)
4. For each case: call `WorkerTestRunner.run()`, score, persist result
5. Update run summary with aggregated stats

**Scoring methods:**

| Method | Logic | Pass threshold |
|--------|-------|----------------|
| `field_match` | Fraction of expected fields matching actual output. Strings compared case-insensitively. Lists scored by subset overlap. | score ≥ 0.5 |
| `exact_match` | 1.0 if `expected == actual`, else 0.0 | score ≥ 0.5 |

**Concurrency model:** `asyncio.gather()` with `asyncio.Semaphore(max_concurrency)`.
Nonlocal counters (`passed`, `failed`, `total_latency`) are safe because the
event loop is single-threaded — the semaphore only bounds concurrent backend
calls, not parallel threads.

### ConfigManager (`config_manager.py`)

CRUD for worker and pipeline YAML configs, backed by filesystem with optional
DuckDB version tracking.

**Workers:**

| Method | What it does |
|--------|-------------|
| `list_workers()` | Glob `configs/workers/*.yaml`, skip `_template.yaml`, return name/description/tier/kind |
| `get_worker(name)` | Load and parse YAML via `load_config()` |
| `get_worker_yaml(name)` | Return raw YAML text (for the editor textarea) |
| `save_worker(name, config)` | Validate via `validate_worker_config()`, write YAML, save version to DB |
| `clone_worker(src, new)` | Load source, change name, save as new |
| `delete_worker(name)` | Delete YAML file |
| `get_worker_version_history(name)` | Query DB for all versions |

**Pipelines:**

| Method | What it does |
|--------|-------------|
| `list_pipelines()` | Glob `configs/orchestrators/*.yaml`, return name/stage_count |
| `get_pipeline(name)` | Load and parse YAML |
| `save_pipeline(name, config)` | Validate via `validate_pipeline_config()`, write YAML |

**File layout convention:** Worker configs live in `configs/workers/{name}.yaml`.
Pipeline configs live in `configs/orchestrators/{name}.yaml`.  The `configs_dir`
constructor arg points to the parent of both.

### PipelineEditor (`pipeline_editor.py`)

Stateless operations on pipeline config dicts.  All methods are `@staticmethod`,
take a config dict, and return a modified deep copy.  No filesystem I/O.

| Method | What it does |
|--------|-------------|
| `get_dependency_graph(config)` | Compute deps + execution levels using `PipelineOrchestrator._infer_dependencies()` and `_build_execution_levels()` |
| `insert_stage(config, stage_def, after)` | Insert a stage after a named stage (or at end) |
| `remove_stage(config, stage_name)` | Remove a stage; raises `ValueError` if other stages depend on it |
| `swap_worker(config, stage_name, new_type, new_tier)` | Replace `worker_type` (and optionally `model_tier`) on a stage |
| `add_parallel_branch(config, stage_def)` | Append a stage with only `goal.*` input mappings (Level 0) |
| `validate(config)` | `validate_pipeline_config()` + cycle detection via `_build_execution_levels()` |

**Dependency validation:** `remove_stage()` checks both `input_mapping` path
references and explicit `depends_on` lists.  `add_parallel_branch()` rejects
stages whose `input_mapping` references existing stage names (must reference only
`goal.*`).

### WorkshopDB (`db.py`)

DuckDB-backed persistence.  Default path: `~/.loom/workshop.duckdb`.
Use `:memory:` for tests.

**Tables:**

| Table | Purpose | Key columns |
|-------|---------|-------------|
| `worker_versions` | Config snapshot history | `worker_name`, `config_hash` (SHA-256 prefix), `config_yaml` |
| `eval_runs` | Eval suite execution summary | `worker_name`, `tier`, `status`, `passed_cases`/`failed_cases`, `avg_latency_ms` |
| `eval_results` | Per-case eval results | `run_id`, `case_name`, `input_payload`, `expected_output`, `actual_output`, `score`, `passed` |
| `worker_metrics` | Aggregated live metrics | `worker_name`, `tier`, `request_count`, `success_count`, `avg_latency_ms`, `p95_latency_ms` |

**Version deduplication:** `save_worker_version()` hashes the YAML content
(SHA-256, first 16 chars) and skips insertion if a version with the same
`(worker_name, config_hash)` already exists.  This means saving an unchanged
config is a no-op.

**Comparison:** `compare_eval_runs(run_id_a, run_id_b)` joins results by
`case_name` and returns a side-by-side structure for A/B display.

---

## Web layer

### Technology stack

| Layer | Technology | Role |
|-------|-----------|------|
| Server | FastAPI | Async routes, form handling, JSON responses |
| Templates | Jinja2 | Server-rendered HTML pages |
| Interactivity | HTMX 2.0 | Async form submissions (test bench), partial page updates |
| Styling | Pico CSS 2.0 | Classless semantic HTML styling |
| Custom CSS | `workshop.css` | Pipeline graph layout, loading indicators, small buttons |

### Route map

| Method | Path | Handler | Template | Description |
|--------|------|---------|----------|-------------|
| GET | `/` | `root` | — | Redirect to `/workers` |
| GET | `/health` | `health` | — | JSON: `{status, backends}` |
| GET | `/workers` | `workers_list` | `workers/list.html` | Worker table |
| GET | `/workers/{name}` | `worker_detail` | `workers/detail.html` | Config editor + version history |
| POST | `/workers/{name}` | `worker_save` | — | Save edited YAML (redirect 303) |
| POST | `/workers/{name}/clone` | `worker_clone` | — | Clone worker (redirect 303) |
| GET | `/workers/{name}/test` | `worker_test` | `workers/test.html` | Test bench form |
| POST | `/workers/{name}/test/run` | `worker_test_run` | `partials/test_result.html` | HTMX: execute test, return result card |
| GET | `/workers/{name}/eval` | `worker_eval` | `workers/eval.html` | Eval dashboard + run form |
| POST | `/workers/{name}/eval/run` | `worker_eval_run` | — | Run eval suite (redirect 303) |
| GET | `/workers/{name}/eval/{run_id}` | `worker_eval_detail` | `workers/eval_detail.html` | Per-case results table |
| GET | `/pipelines` | `pipelines_list` | `pipelines/list.html` | Pipeline table |
| GET | `/pipelines/{name}` | `pipeline_detail` | `pipelines/editor.html` | Dep graph + stage operations |
| POST | `/pipelines/{name}/stage` | `pipeline_stage_edit` | — | Insert/remove/swap/branch (redirect 303) |
| GET | `/pipelines/{name}/graph` | `pipeline_graph` | — | JSON: dependency graph |

### HTMX pattern

Only the test bench uses HTMX for partial updates.  The flow:

1. User fills payload JSON and selects tier in `workers/test.html`
2. Form has `hx-post="/workers/{name}/test/run"` and `hx-target="#test-result"`
3. Server calls `WorkerTestRunner.run()` (may take seconds for LLM call)
4. Server returns `partials/test_result.html` — an `<article>` card with
   PASS/FAIL badge, token counts, output JSON, validation errors, raw response
5. HTMX swaps the card into `#test-result` div without a full page reload
6. Loading indicator `#spinner` shows `aria-busy="true"` during the request

All other forms use standard POST → 303 redirect → GET (PRG pattern).

### Template hierarchy

```
base.html                       # <html>, <nav>, <main>, <footer>
├── workers/list.html           # Table of workers
├── workers/detail.html         # YAML editor + clone + version history
├── workers/test.html           # Test bench form + #test-result target
├── workers/eval.html           # Eval form + past runs table
├── workers/eval_detail.html    # Per-case results + expandable details
├── pipelines/list.html         # Table of pipelines
└── pipelines/editor.html       # Dep graph + 4 stage operation forms

partials/
└── test_result.html            # HTMX fragment (no base.html extends)
```

All full-page templates extend `base.html` and set `active_nav` for nav
highlighting.  The partial template is standalone (no `{% extends %}`).

---

## CLI entry point

```bash
uv run loom workshop [OPTIONS]
```

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | `8080` | HTTP server port |
| `--host` | `127.0.0.1` | Bind address |
| `--configs-dir` | `configs/` | Root directory for worker/pipeline YAML |
| `--db-path` | `~/.loom/workshop.duckdb` | DuckDB database path |
| `--nats-url` | None | NATS URL for live metrics (optional) |

The CLI command creates the app via `create_app()` and runs it under Uvicorn.

### LLM backend resolution

Backends are resolved from environment variables via `build_backends_from_env()`:

| Env var | Tier | Backend |
|---------|------|---------|
| `OLLAMA_URL` | `local` | `OllamaBackend` |
| `OLLAMA_MODEL` | — | Override Ollama model (default: `llama3.2:3b`) |
| `ANTHROPIC_API_KEY` | `standard` + `frontier` | `AnthropicBackend` |
| `FRONTIER_MODEL` | — | Override frontier model (default: `claude-opus-4-20250514`) |

If no env vars are set, `backends` is empty and all test/eval runs will fail
with "No backend for tier" errors.  The `/health` endpoint reports available
backends.

---

## Data model

### DuckDB schema (ER diagram)

```
worker_versions           eval_runs                 eval_results
─────────────────         ─────────────             ──────────────
id (PK)                   id (PK)                   id (PK)
worker_name          ┌──▶ worker_version_id    ┌──▶ run_id (FK)
config_hash (UNIQUE) │    worker_name          │    case_name
config_yaml          │    tier                 │    input_payload
created_at           │    started_at           │    expected_output
description          │    completed_at         │    actual_output
                     │    status               │    raw_response
                     │    total_cases          │    validation_errors
                     │    passed_cases         │    score
                     │    failed_cases         │    score_details
                     │    avg_latency_ms       │    latency_ms
                     │    avg_prompt_tokens    │    prompt_tokens
                     │    avg_completion_tokens│    completion_tokens
                     │    metadata             │    model_used
                     │                         │    passed
                     │                         │    error
                     │                         │
worker_metrics       │                         │
──────────────       │                         │
id (PK)              └── (joined via           └── (FK relationship)
worker_name              worker_version_id)
tier
recorded_at
window_seconds
request_count
success_count
failure_count
avg_latency_ms
p95_latency_ms
avg_prompt_tokens
avg_completion_tokens
```

### Unique constraints

- `worker_versions`: `UNIQUE (worker_name, config_hash)` — deduplicates
  identical configs.
- All primary keys are UUID v4 strings.

---

## Reused Loom internals

The Workshop reuses core Loom functions rather than reimplementing them.  This
keeps the test bench semantically identical to production worker execution.

| Function / Class | Source | Used by Workshop for |
|-----------------|--------|---------------------|
| `execute_with_tools()` | `worker/runner.py` | Full LLM call with tool-use loop |
| `_extract_json()` | `worker/runner.py` | JSON parsing from LLM response |
| `_load_tool_providers()` | `worker/runner.py` | Loading silo-based tools |
| `build_backends_from_env()` | `worker/backends.py` | Resolving available LLM backends |
| `validate_input()` | `core/contracts.py` | Input schema validation |
| `validate_output()` | `core/contracts.py` | Output schema validation |
| `validate_worker_config()` | `core/config.py` | Worker config structure validation |
| `validate_pipeline_config()` | `core/config.py` | Pipeline config validation |
| `load_config()` | `core/config.py` | YAML loading |
| `load_knowledge_silos()` | `worker/knowledge.py` | Knowledge silo injection |
| `load_knowledge_sources()` | `worker/knowledge.py` | Legacy knowledge injection |
| `WorkspaceManager` | `core/workspace.py` | File-ref resolution |
| `PipelineOrchestrator._infer_dependencies()` | `orchestrator/pipeline.py` | Dependency graph computation |
| `PipelineOrchestrator._build_execution_levels()` | `orchestrator/pipeline.py` | Topological sort for execution levels |

---

## Enhancement guide

### Adding a new scoring method

1. Write a function in `eval_runner.py` matching the signature:
   ```python
   def _score_my_method(expected: dict, actual: dict) -> tuple[float, dict]:
       # Return (score_0_to_1, {"method": "my_method", ...details})
   ```

2. Add a branch in `EvalRunner.run_suite()`:
   ```python
   if scoring == "my_method":
       score_fn = _score_my_method
   ```

3. Add an `<option>` in `workers/eval.html` scoring `<select>`.

### Adding a new page

1. Create template in `templates/{section}/{page}.html` extending `base.html`.
2. Add route handler in `app.py` inside `create_app()`.
3. If it needs HTMX partial updates, add a `partials/` template and use
   `hx-post`/`hx-target`.

### Adding a new pipeline stage operation

1. Add a `@staticmethod` method in `PipelineEditor`.
2. Add an `elif action == "my_action"` branch in `pipeline_stage_edit()` route.
3. Add a `<details>` form block in `pipelines/editor.html`.

### Adding live metrics via NATS

The `nats_url` parameter is plumbed through `create_app()` but not yet wired.
Implementation plan:

1. Create `MetricsCollector` class that subscribes to `loom.results.*`.
2. On each result, compute window aggregates and call
   `WorkshopDB.save_worker_metric()`.
3. Initialize in `create_app()` when `nats_url` is not None.
4. Add a `/metrics` page with time-series charts (latency, throughput,
   error rate) per worker.

### Adding LLM-as-judge scoring

1. Add a scoring function that takes expected + actual and dispatches to an
   LLM backend with a judging prompt.
2. The judge backend should be configurable separately (e.g., always use
   `frontier` tier for judging regardless of the worker tier under test).
3. Cache judge results in `eval_results.score_details` JSON column.

### Extending the frontend

The Workshop uses **Pico CSS** for classless styling — semantic HTML elements
are styled automatically without CSS classes.  Custom CSS in `workshop.css` is
minimal: pipeline graph flexbox layout, HTMX indicator toggle, small button
variant.

For richer interactivity (e.g., drag-and-drop pipeline editor, live charts):

1. Keep the HTMX pattern for server-driven updates.
2. For client-side-only widgets, add `<script>` blocks in specific templates.
3. Avoid introducing a build step — the Workshop should remain zero-build.

---

## Testing

Workshop tests are in `tests/`:

| File | What it tests |
|------|--------------|
| `test_workshop_runner.py` | `WorkerTestRunner` with mock backends |
| `test_workshop_db.py` | `WorkshopDB` schema, CRUD, dedup, comparison |
| `test_workshop_eval.py` | `EvalRunner` scoring, concurrency, DB persistence |
| `test_workshop_config.py` | `ConfigManager` CRUD, validation, cloning |
| `test_workshop_pipeline_editor.py` | `PipelineEditor` insert/remove/swap/branch/validate |

All tests use in-memory DuckDB (`:memory:`) and mock LLM backends.  No
infrastructure needed.

```bash
# Run workshop tests only
uv run pytest tests/test_workshop_*.py -v

# Run all tests
uv run pytest tests/ -v -m "not integration"
```

---

*For general Loom architecture, see [Architecture](ARCHITECTURE.md).
For building workers and pipelines, see [Building Workflows](building-workflows.md).*
