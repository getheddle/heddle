# Wire conformance fixtures (v1)

Language-neutral examples of heddle wire messages, valid and invalid.
An SDK in any language proves it speaks the v1 wire contract by passing
every fixture here. Agreement with the JSON Schemas alone is not proof.

The Python runtime is held to the same files by
`tests/test_wire_fixtures.py`: for every fixture, the committed schemas
and `heddle.core.envelope.parse` must give the same verdict at the same
layer.

## Layout

- `manifest.json` is the index. Drive your tests from it rather than from
  directory listings.
  - `frame_schema`: the frame schema file (`wire_envelope.schema.json`).
  - `payload_types`: maps each `payload_type` discriminator to its body
    schema file. Each body schema also states it in `x-heddle-payload-type`.
  - `fixtures[]`: one entry per file, giving `expect` (`valid` or
    `invalid`), `payload_type`, a `description`, and, for invalid
    fixtures, `rejected_at`. A valid fixture may list `may_drop`: dotted
    paths (for example `payload.x_future_field`) that a receiver is
    allowed to drop on round-trip.
- `valid/`: complete wire messages that must be accepted.
- `invalid/`: messages that must be rejected.

The schemas are JSON Schema **draft 2020-12** (each declares `$schema`;
references use `$defs`). Configure your validator or code generator for
that draft, and turn on `format` checking: by default many validators
treat `format: date-time` as an annotation and do not enforce it.

## What to assert

**Valid fixtures**

1. The frame validates, then the body (`payload`) validates against the
   model selected by `payload_type`.
2. Round-trip: deserialize, then re-serialize. The result must equal the
   fixture by value, ignoring only the paths listed in `may_drop`. Every
   `_`-prefixed top-level key (the Middleware Lane, for example
   `_trace_context`) must survive unchanged.

**Invalid fixtures.** The message must be rejected at the layer named by
`rejected_at`:

| `rejected_at` | Meaning |
|---|---|
| `frame` | The frame itself is invalid (missing or ill-typed field, unknown non-`_` key, bad timestamp). |
| `body` | The frame is valid; the body fails its model. |
| `dispatch` | Frame valid; no body model is registered for `payload_type`. |

An SDK registers exactly the `payload_types` listed in the manifest.
Any other `payload_type` is a `dispatch` rejection, including
`events.*` types that a Python process with `heddle.contrib.events`
loaded would accept.

Following Invariant 8, a worker or router that receives any of these on
the bus logs a warning and skips it. It does not crash.

## Comparison rules

- Compare JSON by value, not bytes: key order, whitespace, and string
  escaping are not significant.
- Compare timestamps as instants. Timestamps are RFC 3339 with a
  timezone offset. Parsers must accept fractional seconds (the Python
  runtime emits microseconds for generated times) and any offset, not
  only `Z`. Emitting `+00:00` instead of `Z`, or a different number of
  fractional digits, is conformant if the instant is equal.
- Every fixture spells out every field, including defaults and `null`s.
  **Always emit the generated identity and time fields**: `message_id`,
  `occurred_at` and `recorded_at` on the frame, and `task_id` and
  `goal_id` on the bodies. A receiver fills a missing one with a freshly
  generated value, so it can never round-trip. The two frame timestamps
  are filled together: if both are missing, both get the same fresh
  time; if only one is present, the missing one copies it. An SDK may
  omit fields
  whose default is static (`null`, `{}`, an enum default) only if it
  still compares equal after those defaults are filled back in.
- Numbers: integers stay integers (`processing_time_ms`, token counts).
  Values inside `input`, `output`, `metadata` and `context` are opaque
  JSON and must round-trip as given.

## Versioning rules for bodies

- **Receivers must accept unknown body keys.** They may drop them, and the
  Python runtime does. An unknown body key is never a reason to reject a
  message. This lets a newer sender add a field without breaking an older
  receiver. The frame is different: unknown top-level keys are rejected
  unless `_`-prefixed.
- **Within v1, bodies grow only by optional fields with defaults.** A new
  required field, a removed field, or a changed meaning is a breaking
  change, and it needs a new `payload_type` rather than an edit to an
  existing body.
- Cross-cutting metadata (tracing and similar) belongs in the frame's
  Middleware Lane (`_`-prefixed keys), not in bodies.

## Not specified here

- **Lenient input in the Python runtime.** The schemas are the contract.
  Today the Python runtime also accepts some inputs the schemas reject
  (for example a timestamp without an offset, or a numeric field sent as
  a string). Do not rely on that: send what the schemas allow.

- **Preserving unknown body keys through intermediaries.** Dropping them
  is allowed today. Requiring receivers to keep them when re-sending
  would be a compatible tightening that can be adopted later.
- **`contrib.events` bodies** (`events.Event`, `events.Command`,
  `events.Rejection`). They are experimental and not part of the exported
  contract.
- Transport: NATS subjects and queue groups are in
  `docs/foreign-actors.md`.
