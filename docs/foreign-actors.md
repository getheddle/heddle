# Foreign-Language Actors — The Wire Protocol

**Audience:** authors of Heddle actors written in languages other than
Python (.NET, Swift, JVM, Go, Rust, etc.).

Heddle's framework is Python, but the **wire protocol** between actors
is language-agnostic: NATS subjects + JSON messages. This document
specifies the contract a non-Python actor must implement to participate
in a Heddle bus.

!!! tip "Reference SDKs"
    The companion [getheddle/heddle-sdk](https://github.com/getheddle/heddle-sdk)
    repository packages this protocol for .NET, Swift, and JVM. The rendered SDK
    docs live at <https://getheddle.dev/heddle-sdk/>.

## The envelope

Every message on the bus is a JSON object with two layers:

- **The frame** (`WireEnvelope`, `heddle.core.envelope`): identity,
  timestamps, origin, causality, and a `payload_type` discriminator.
  It is the same for every message type.
- **The body** (in `payload`): the typed message selected by
  `payload_type`. Core bodies are `core.TaskMessage`, `core.TaskResult`,
  and `core.OrchestratorGoal` (Pydantic models in `heddle.core.messages`).
  Each body carries its worker-specific data (`input` / `output`), shaped
  by the worker's `input_schema` / `output_schema` and opaque to the
  framework.

Parsing has two steps: validate the frame, then pick the body model by
`payload_type` and validate `payload` against it. An unknown
`payload_type` is rejected; it is not passed through.

The canonical JSON Schemas are exported to `schemas/v1/` and gated by a
CI drift check. They are the authoritative wire contract:

| File | Describes |
|---|---|
| `wire_envelope.schema.json` | The frame. Unknown top-level keys are rejected unless `_`-prefixed. |
| `task_message.schema.json` | Body for `payload_type: "core.TaskMessage"` |
| `task_result.schema.json` | Body for `payload_type: "core.TaskResult"` |
| `orchestrator_goal.schema.json` | Body for `payload_type: "core.OrchestratorGoal"` |

Each body schema states its discriminator in `x-heddle-payload-type`.
`schemas/v1/fixtures/` holds language-neutral valid and invalid wire
messages, and its `manifest.json` gives the expected outcome and the
rejecting layer for each. Run your serializer and validator against them;
see `schemas/v1/fixtures/README.md`.

**Middleware Lane.** Top-level frame keys starting with `_` (for example
`_trace_context`, W3C propagation headers) are framework metadata. They
are never declared in a schema, and they must survive parse and
re-serialize unchanged. Keep them out of the body and out of `metadata`.

### TaskMessage (request)

```text
heddle.tasks.incoming
       ▲
       │ (router subscribes; dispatches based on worker_type + tier)
       │
heddle.tasks.{worker_type}.{tier}
       ▲
       │ (processor workers subscribe with queue group processors-{worker_type})
       │
       └── WireEnvelope ─── JSON object ─────────────────────┐
                                                              │
   message_id           str (UUIDv7)                          │
   payload_type         "core.TaskMessage"                    │
   origin               str | null                            │ FRAME
   correlation_id       str | null                            │
   causation_id         str | null                            │
   occurred_at          str  (RFC 3339, with offset)          │
   recorded_at          str  (RFC 3339, with offset)          │
   _trace_context       object  (optional, W3C headers)       │
   ─────────────────────────────────────────────────────────  ┘
   payload              TaskMessage body:                     ╮
     task_id            str (UUID)                            │
     parent_task_id     str | null  (goal_id when from orch)  │
     worker_type        str                                   │ BODY
     model_tier         "local" | "standard" | "frontier"     │
     priority           "low" | "normal" | "high" | "critical"│
     request_id         str | null                            │
     metadata           object                                │
     input              object  ← validated against           │
                                  worker.input_schema         ╯
```

### TaskResult (response)

```text
heddle.results.{parent_task_id or "default"}
       ▲
       │ (orchestrator subscribed before publishing TaskMessage)
       │
       └── WireEnvelope ─── JSON object ─────────────────────┐
                                                              │
   (same frame fields; payload_type "core.TaskResult")        │ FRAME
   _* keys              every `_` key from the TaskMessage    │
   ─────────────────────────────────────────────────────────  ┘
   payload              TaskResult body:                      ╮
     task_id            str  (matches TaskMessage.task_id)    │
     parent_task_id     str | null  (matches TaskMessage)     │
     worker_type        str                                   │
     status             "completed" | "failed"                │ BODY
                        | "pending" | "processing"            │
     error              str | null                            │
     model_used         str | null                            │
     token_usage        object  ({"prompt_tokens": int, ...}) │
     metadata           object                                │
     processing_time_ms int                                   │
     output             object | null  ← validated against    │
                                         worker.output_schema ╯
```

Bodies carry no timestamps; the frame's `occurred_at` / `recorded_at`
replace the former `created_at` / `completed_at`.

The worker copies every `_` key from the TaskMessage frame onto the
TaskResult frame (DESIGN_INVARIANTS #22). When OpenTelemetry is enabled,
`_trace_context` is then replaced with the span the worker's actor opened
for the message, so a consumer-side span parents under it. The router
forwards a task's frame, so `_` keys, `origin`, `correlation_id` and
`causation_id` reach the worker as the producer sent them. Orchestrators copy a goal's `_` keys onto the subtasks they
dispatch for it, so a key set on a goal reaches every worker.

## Generating typed wrappers in your language

If you are targeting .NET, Swift, or JVM, start with the reference SDKs:
[.NET](https://getheddle.dev/heddle-sdk/DOTNET/),
[Swift](https://getheddle.dev/heddle-sdk/SWIFT/), or
[JVM](https://getheddle.dev/heddle-sdk/JVM/). The schema-generation
flow below is for SDK maintainers and for languages that do not yet have a
packaged SDK.

The Pydantic-exported JSON Schemas in `schemas/v1/` plug straight into
off-the-shelf code generators. No custom IDL or designer tool — the
wire contract IS the schema. Generate one type for the frame
(`wire_envelope.schema.json`) and one per body, then implement the
two-step parse by hand: frame first, then dispatch on `payload_type`.
The examples below generate a body type.

**Swift** (idiomatic `Codable` types):

```bash
quicktype \
    --src schemas/v1/task_message.schema.json \
    --src-lang schema \
    --lang swift \
    --top-level TaskMessage \
    -o Sources/HeddleActor/TaskMessage.swift
```

**.NET / C#** (with `System.Text.Json` attributes):

```bash
quicktype \
    --src schemas/v1/task_message.schema.json \
    --src-lang schema \
    --lang csharp \
    --framework SystemTextJson \
    --top-level TaskMessage \
    -o src/Heddle.Actor/TaskMessage.cs
```

**Other languages** — `quicktype` supports TypeScript, Kotlin, Go,
Rust, Java, Ruby, Python (dataclasses), and more. Use the same
invocation, varying `--lang`. For Python projects that want their own
typed view, `datamodel-code-generator` produces Pydantic models from
the same JSON Schemas.

Every SDK derives its types from the same `schemas/v1/*.schema.json`
files, which are generated from the canonical Pydantic models (CI fails
on drift). Schema agreement alone does not prove wire compatibility, so
an SDK claims conformance only when it passes every fixture in
`schemas/v1/fixtures/`.

!!! warning "SDK status"
    Since the `WireEnvelope` reshape (on `main`; first released in
    v0.10.0), the reference SDKs in `heddle-sdk` still speak the
    pre-`WireEnvelope` flat format and are **not** wire-compatible with it. Migration is tracked in
    [heddle-sdk#4](https://github.com/getheddle/heddle-sdk/issues/4) and
    [heddle-sdk#5](https://github.com/getheddle/heddle-sdk/issues/5).

## NATS subjects

| Subject | Direction | Notes |
| --- | --- | --- |
| `heddle.tasks.incoming` | client → router | Where orchestrators / clients publish `TaskMessage`s for routing. Foreign actors rarely subscribe here directly. |
| `heddle.tasks.{worker_type}.{tier}` | router → worker | Processor workers subscribe with **queue group name = `processors-{worker_type}`** so multiple replicas of the same worker load-balance via NATS queue-group semantics. |
| `heddle.tasks.dead_letter` | router → operator | Unroutable or rate-limited messages land here. Foreign actors don't publish here; the router does. |
| `heddle.results.{parent_task_id}` | worker → orchestrator | Each goal opens a unique result subject; the worker echoes back to it. The orchestrator subscribes BEFORE publishing the task (Invariant 17). |
| `heddle.results.default` | worker → standalone caller | Used when a `TaskMessage` has no `parent_task_id`. |
| `heddle.control.reload` | operator → all actors | Optional config hot-reload broadcast. Foreign actors MAY subscribe to re-read their config. |

## Required behaviours

A foreign actor MUST observe these to interoperate cleanly with the
Python framework:

1. **Queue-group subscription.** Subscribe to
   `heddle.tasks.{worker_type}.{tier}` with
   `queue_group=processors-{worker_type}`. Without the queue group,
   every replica receives every task.
2. **Reset between tasks** (Invariant 1). No state may carry from one
   task to the next inside one actor process. The Python framework
   enforces this via a `reset()` call in a `finally` block; foreign
   actors must achieve the same effect (clear per-task locals before
   the next `recv()` call).
3. **Skip-and-log on malformed input** (Invariant 8). If the bytes
   don't parse as JSON, the text is not I-JSON (a member name repeated
   in any object, or `NaN`/`Infinity`; see
   `schemas/v1/fixtures/README.md`), the frame is invalid, `payload_type` is not
   `core.TaskMessage`, or the body doesn't conform to `TaskMessage`, log a
   warning and continue the subscription loop. Do not crash the
   process; do not retry the bad message — the publisher needs to
   fix its output.
4. **Subscribe-before-publish for the result subject** is *the
   orchestrator's* responsibility, not the worker's. Workers just
   publish to `heddle.results.{parent_task_id}` when done.
5. **JSON Schema validation** is intentionally shallow (Invariant 5):
   required-field presence + top-level type checks. Foreign SDKs
   SHOULD implement the same shallow validation against
   `input_schema` / `output_schema` from the worker's config.
   Implementing full JSON Schema validation is allowed but produces
   stricter behaviour than the Python actors; document the divergence
   if you do.
6. **Middleware Lane propagation.** If the incoming message has
   top-level keys starting with `_` (e.g. `_trace_context`), extract
   any you understand (like W3C Trace Context) and **always include
   every `_`-prefixed key verbatim** on the `TaskResult`. Do not put
   these under `metadata`; they belong at the top level of the JSON
   envelope.

## Scope — what foreign actors are (and aren't)

Foreign actors are positioned as **`processor` workers**: they run
compute, ML inference, transformations, native-library calls, etc.
The framework supports them as first-class participants on the bus.

What they **are not** (today, by design):

- **LLM workers.** Heddle's LLM backends (Anthropic, OpenAI, Ollama,
  LM Studio) are Python-native and offer features (retry policy,
  reasoning-content rescue, thinking-block surface) that haven't
  been replicated in other languages. A foreign actor that needs LLM
  inference should call a sibling Python LLM worker via the bus.
- **Knowledge-silo consumers.** `docproc`, `rag`, `lancedb`, etc. are
  Python-side abstractions over file formats and embedding stores.
  Foreign actors that need these capabilities call sibling Python
  workers; they don't reimplement silo access.
- **Tool providers.** Same shape as silos.

This scope keeps the foreign-actor wire surface small and well-defined.
If you find yourself wanting to reimplement an LLM backend or a silo
adapter in .NET / Swift, the cleaner shape is a Python proxy worker
that exposes the capability over the bus.

## Configuration

A foreign actor's worker config YAML lives alongside Python worker
configs in `configs/workers/<name>.yaml`. The fields the router and
orchestrator care about are unchanged:

```yaml
name: image_classifier              # worker_type
worker_kind: processor              # foreign actors are always 'processor'
default_model_tier: local
input_schema:
  type: object
  required: [image_url]
  properties:
    image_url: {type: string}
output_schema:
  type: object
  required: [label, confidence]
  properties:
    label: {type: string}
    confidence: {type: number}
implementation:                     # OPTIONAL — interpreted by Workshop
  runtime: dotnet                   #   tooling so it can offer the
  entry: ./bin/Heddle.ImageClassifier  #   right lifecycle affordances
                                       #   (test-run, eval-runs, etc.)
                                       #   without trying to import a
                                       #   Python module.
```

The `implementation` block is informational — the framework doesn't
launch foreign workers itself. Run them under systemd, Docker,
launchd, or whatever your deploy target supports; they connect to
NATS the same way Python workers do.

## Reference SDKs

The companion [getheddle/heddle-sdk](https://github.com/getheddle/heddle-sdk)
repository is the reference implementation of this protocol outside Python.
It currently includes:

- [.NET SDK](https://getheddle.dev/heddle-sdk/DOTNET/) — `Heddle.Sdk`
  client and actor runtime for processor workers.
- [Swift SDK](https://getheddle.dev/heddle-sdk/SWIFT/) — `HeddleActor`
  client and actor runtime for Swift services.
- [JVM SDK](https://getheddle.dev/heddle-sdk/JVM/) — `heddle-sdk-core`
  client and actor runtime for Kotlin and Java services.
- [SDK examples](https://getheddle.dev/heddle-sdk/EXAMPLES/) — minimal
  processor actors and callers that match this wire contract.

For other languages, the wire spec above plus `schemas/v1/` is sufficient to
build a small SDK. The protocol surface is intentionally narrow.

## See also

- `schemas/v1/` (in the repository) — authoritative JSON Schemas, CI-checked.
- [Heddle SDK docs](https://getheddle.dev/heddle-sdk/) — .NET and Swift reference SDK documentation.
- [getheddle/heddle-sdk](https://github.com/getheddle/heddle-sdk) — SDK source repository.
- [Gateway Actors](gateway-actors.md) — for non-NATS protocols (MQTT, HTTP, IoT).
- [Design Invariants](DESIGN_INVARIANTS.md) — framework-safety contracts (1, 5, 8, 17 in particular apply to foreign actors).
- [ADR-001](adr/001-stateless-workers.md) — why the reset-between-tasks invariant exists.
etheddle/heddle-sdk) — SDK source repository.
- [Gateway Actors](gateway-actors.md) — for non-NATS protocols (MQTT, HTTP, IoT).
- [Design Invariants](DESIGN_INVARIANTS.md) — framework-safety contracts (1, 5, 8, 17 in particular apply to foreign actors).
- [ADR-001](adr/001-stateless-workers.md) — why the reset-between-tasks invariant exists.
