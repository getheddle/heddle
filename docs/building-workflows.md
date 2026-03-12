# Building AI Workflows with Loom

This guide walks you through building your own AI-powered workflows using Loom. By the end, you'll know how to create workers, chain them into pipelines, and use features like knowledge injection and file-ref resolution.

## Core concepts

Loom is built on an **actor model** where work is split across independent, stateless actors communicating via NATS messages.

**Workers** are the building blocks. Each worker does exactly one thing — summarize text, classify a document, extract fields, convert a PDF. Workers are configured entirely through YAML files: a system prompt, input/output schemas, and a model tier. They process one task, publish a result, and reset. No state carries between tasks.

There are two kinds of workers:

- **LLM workers** call a language model (Ollama, Anthropic, OpenAI-compatible). They're defined by a system prompt and I/O schemas.
- **Processor workers** run non-LLM code (Docling for PDFs, ffmpeg for media, scikit-learn, custom Python). They implement a `ProcessingBackend` interface.

**Orchestrators** coordinate workers. A `PipelineOrchestrator` runs stages sequentially, wiring outputs from one stage as inputs to the next. A `OrchestratorActor` uses an LLM to dynamically decompose goals into subtasks.

**The router** sits between orchestrators and workers. It's deterministic (no LLM) — it reads the `worker_type` and `model_tier` from each task message and publishes it to the right NATS subject. It enforces rate limits and sends unroutable tasks to a dead-letter subject.

```
Goal → Orchestrator → Router → Worker(s) → Results → Orchestrator → Final answer
```

## Prerequisites

Before building workflows, complete the setup in the main README:

1. Python 3.11+ with `pip install -e ".[dev]"`
2. NATS server running (e.g., `docker run -d -p 4222:4222 nats:2.10-alpine`)
3. At least one LLM backend (Ollama recommended: `ollama pull llama3.2:3b`)

Verify the setup:

```bash
pytest tests/ -v -m "not integration"   # all unit tests should pass
```

## Part 1: Create an LLM worker

LLM workers are the simplest way to add AI capability. You define the worker entirely in YAML — no Python code needed.

### Step 1: Copy the template

```bash
cp configs/workers/_template.yaml configs/workers/entity_extractor.yaml
```

### Step 2: Define the worker

Edit the file. The key sections are the system prompt and I/O schemas:

```yaml
name: "entity_extractor"
description: "Extracts named entities (people, places, orgs) from text."

system_prompt: |
  You are an entity extraction agent. Extract named entities from the input text.

  INPUT FORMAT:
  You will receive a JSON object:
  - text (string): The text to analyze

  OUTPUT FORMAT:
  Respond with ONLY a JSON object:
  {
    "people": ["name1", "name2"],
    "places": ["place1"],
    "organizations": ["org1"],
    "count": <total number of entities>
  }

  RULES:
  - If no entities found, return empty arrays and count: 0
  - Deduplicate entities (same name mentioned twice = one entry)
  - Never output anything except the JSON object

input_schema:
  type: object
  required: [text]
  properties:
    text:
      type: string
      minLength: 1

output_schema:
  type: object
  required: [people, places, organizations, count]
  properties:
    people:
      type: array
      items:
        type: string
    places:
      type: array
      items:
        type: string
    organizations:
      type: array
      items:
        type: string
    count:
      type: integer

default_model_tier: "local"
max_output_tokens: 1000
reset_after_task: true
timeout_seconds: 30
```

The schemas are enforced at runtime — if the LLM returns output that doesn't match `output_schema`, the task fails with a validation error rather than propagating garbage downstream.

### Step 3: Run the worker

```bash
loom worker --config configs/workers/entity_extractor.yaml --tier local
```

The worker subscribes to `loom.tasks.entity_extractor.local` and waits for tasks.

### Step 4: Test it

In another terminal (with the router running):

```bash
loom submit "Extract entities from this text" \
  --context text="The United Nations was founded in San Francisco in 1945 by Franklin Roosevelt." \
  --nats-url nats://localhost:4222
```

## Part 2: Create a processor worker (non-LLM)

Processor workers wrap Python libraries that aren't LLMs. Use these for document conversion, media processing, data transformation, or any deterministic computation.

### Step 1: Implement a ProcessingBackend

For async-native backends, implement `ProcessingBackend`:

```python
from loom.worker.processor import ProcessingBackend

class MyAsyncBackend(ProcessingBackend):
    async def process(self, payload, config):
        # async work here (API calls, async I/O, etc.)
        result = await some_async_operation(payload["input"])
        return {
            "output": {"result": result},
            "model_used": "my-tool-v1",
        }
```

For synchronous/CPU-bound backends (the common case), use `SyncProcessingBackend`:

```python
from loom.worker.processor import SyncProcessingBackend

class DoclingBackend(SyncProcessingBackend):
    def process_sync(self, payload, config):
        # CPU-bound work — automatically runs in a thread pool
        # so the async event loop stays responsive
        result = heavy_computation(payload["file_ref"])
        return {
            "output": {"extracted_text": result},
            "model_used": "docling",
        }
```

`SyncProcessingBackend` handles the `run_in_executor` boilerplate for you.

### Step 2: Handle errors with BackendError

For structured error handling, subclass `BackendError`:

```python
from loom.worker.processor import BackendError, SyncProcessingBackend

class ConversionError(BackendError):
    """Raised when document conversion fails."""

class MyBackend(SyncProcessingBackend):
    def process_sync(self, payload, config):
        try:
            result = convert(payload["file_ref"])
        except Exception as exc:
            raise ConversionError(f"Conversion failed: {exc}") from exc
        return {"output": result, "model_used": "my-converter"}
```

The `from exc` preserves the original exception chain for debugging.

### Step 3: Configure the worker

```yaml
name: "my_processor"
worker_kind: "processor"
processing_backend: "mypackage.backends.MyBackend"
backend_config:
  workspace_dir: "/tmp/my-workspace"

input_schema:
  type: object
  required: [file_ref]
  properties:
    file_ref:
      type: string

output_schema:
  type: object
  required: [extracted_text]
  properties:
    extracted_text:
      type: string

timeout_seconds: 120
```

### Step 4: Run it

```bash
loom processor --config configs/workers/my_processor.yaml
```

## Part 3: Chain workers into a pipeline

Pipelines run workers in sequence, wiring outputs from one stage as inputs to the next.

### Step 1: Create a pipeline config

```yaml
name: "analysis_pipeline"
timeout_seconds: 300

pipeline_stages:
  - name: "extract"
    worker_type: "doc_extractor"
    tier: "local"
    input_mapping:
      file_ref: "goal.context.file_ref"

  - name: "classify"
    worker_type: "doc_classifier"
    tier: "local"
    input_mapping:
      text_preview: "extract.output.text_preview"
      page_count: "extract.output.page_count"

  - name: "summarize"
    worker_type: "entity_extractor"
    tier: "local"
    input_mapping:
      text: "extract.output.text_preview"
```

The `input_mapping` wires data between stages:

- `"goal.context.file_ref"` — reads from the original goal's context
- `"extract.output.text_preview"` — reads from the `extract` stage's output

### Step 2: Run the pipeline

```bash
# Start all workers that the pipeline needs
loom worker --config configs/workers/entity_extractor.yaml --tier local &
loom processor --config configs/workers/doc_extractor.yaml &

# Start the router
loom router &

# Start the pipeline orchestrator
loom pipeline --config configs/orchestrators/analysis_pipeline.yaml

# Submit a goal
loom submit "Analyze document" --context file_ref=report.pdf
```

## Part 4: Add knowledge context

LLM workers can have domain-specific knowledge injected into their system prompt. This is useful for glossaries, style guides, domain rules, or few-shot examples.

### Step 1: Create a knowledge file

Knowledge files can be Markdown, YAML, or plain text:

```markdown
# configs/knowledge/legal_terms.md

## Key Legal Terms

- **Habeas corpus**: A court order requiring a person to be brought before a judge.
- **Amicus curiae**: A person or organization not party to a case who offers expertise.
- **Certiorari**: A writ seeking judicial review of a lower court's decision.
```

### Step 2: Reference it in the worker config

```yaml
name: "legal_summarizer"
system_prompt: |
  You are a legal document summarizer. Use the reference material
  provided to ensure accurate use of legal terminology.
  ...

knowledge_sources:
  - path: "configs/knowledge/legal_terms.md"
    inject_as: "reference"
```

Two injection modes:

- **`reference`** — Prepends the file contents to the system prompt with a header.
- **`few_shot`** — Formats YAML/JSONL content as numbered input/output examples.

For few-shot examples, structure your YAML like this:

```yaml
# configs/knowledge/classification_examples.yaml
- input: "Contract between Acme Corp and Beta Inc for software development"
  output: "contract"
- input: "Minutes from the Q3 board meeting held on September 15"
  output: "meeting_minutes"
```

## Part 5: Use file-ref resolution

When pipeline stages produce large data (extracted documents, analysis results), they write JSON files to a shared workspace directory rather than inlining everything in NATS messages. LLM workers can automatically resolve these file references and inject the content into their prompt.

### Step 1: Configure the workspace

Add two fields to your LLM worker config:

```yaml
workspace_dir: "/tmp/my-workspace"
resolve_file_refs: ["file_ref"]
```

### Step 2: How it works

When a task arrives with `payload.file_ref = "report_extracted.json"`:

1. The worker reads `/tmp/my-workspace/report_extracted.json`
2. Parses it as JSON
3. Adds `file_ref_content` to the payload with the parsed data
4. Builds the LLM prompt with both the reference and the content

The LLM sees the full extracted data without it traveling through NATS messages.

### Step 3: Use WorkspaceManager in processor backends

Processor backends can use `WorkspaceManager` directly for safe file I/O:

```python
from loom.core.workspace import WorkspaceManager

class MyBackend(SyncProcessingBackend):
    def process_sync(self, payload, config):
        ws = WorkspaceManager(config["workspace_dir"])

        # Safe file resolution (blocks path traversal)
        source = ws.resolve(payload["file_ref"])

        # Process the file...
        result = do_work(source)

        # Write output to workspace
        ws.write_json("result.json", result)

        return {
            "output": {"file_ref": "result.json", "status": "done"},
            "model_used": "my-tool",
        }
```

`WorkspaceManager.resolve()` prevents path traversal attacks — any attempt to reference `../../etc/passwd` raises `ValueError`.

## Part 6: Configure routing rules

The router controls which model tier handles each worker type and enforces rate limits.

Edit `configs/router_rules.yaml`:

```yaml
# Force specific workers to specific tiers
tier_overrides:
  entity_extractor: "local"       # always use Ollama
  legal_summarizer: "standard"    # always use Claude Sonnet

# Per-tier rate limits (token-bucket)
rate_limits:
  local:
    max_concurrent: 4
    tokens_per_minute: 100000
  standard:
    max_concurrent: 10
    tokens_per_minute: 200000
  frontier:
    max_concurrent: 3
    tokens_per_minute: 50000
```

Tasks that exceed rate limits are sent to `loom.tasks.dead_letter` rather than dropped.

## Worker config reference

Full list of fields available in worker YAML configs:

| Field | Required | Default | Description |
|-------|----------|---------|-------------|
| `name` | yes | — | Worker type identifier (matches `worker_type` in task messages) |
| `description` | no | — | Human-readable description |
| `worker_kind` | no | `"llm"` | `"llm"` or `"processor"` |
| `system_prompt` | yes (LLM) | — | The system prompt sent to the LLM |
| `processing_backend` | yes (processor) | — | Fully qualified Python class path |
| `backend_config` | no | `{}` | Dict passed to backend constructor |
| `input_schema` | yes | — | JSON Schema for input validation |
| `output_schema` | yes | — | JSON Schema for output validation |
| `default_model_tier` | no | `"standard"` | `"local"`, `"standard"`, or `"frontier"` |
| `max_input_tokens` | no | `4000` | Max input token budget |
| `max_output_tokens` | no | `2000` | Max output token budget |
| `knowledge_sources` | no | `[]` | List of `{path, inject_as}` for context injection |
| `workspace_dir` | no | — | Workspace directory for file-ref resolution |
| `resolve_file_refs` | no | `[]` | Payload fields to resolve as workspace file refs |
| `reset_after_task` | no | `true` | Always `true` for workers (statelessness is enforced) |
| `timeout_seconds` | no | `60` | Per-task timeout |

## NATS subject conventions

| Subject | Purpose |
|---------|---------|
| `loom.goals.incoming` | Orchestrators subscribe here for new goals |
| `loom.tasks.incoming` | Router subscribes here for task dispatch |
| `loom.tasks.{worker_type}.{tier}` | Workers subscribe here (queue groups for competing consumers) |
| `loom.tasks.dead_letter` | Unroutable or rate-limited tasks land here |
| `loom.results.{goal_id}` | Results flow back to the orchestrator that owns the goal |

## Tips

- **Keep workers narrow.** A worker that does one thing well is better than a worker that tries to do everything. If you need multiple capabilities, create multiple workers and wire them with a pipeline.
- **Test without infrastructure.** All worker logic can be unit-tested without NATS or Redis — mock the `publish` method and call `handle_message()` directly. See `tests/test_worker.py` for examples.
- **Use local tier for development.** Ollama with a small model (llama3.2:3b or command-r7b) gives fast iteration. Switch to standard/frontier tiers when you need better reasoning.
- **Schema validation is your safety net.** It catches malformed LLM output before it propagates to downstream stages. Define schemas tightly.
- **Monitor the dead-letter subject.** Tasks landing on `loom.tasks.dead_letter` indicate routing failures or rate limit hits. Use `nats sub loom.tasks.dead_letter` during development.
