"""Export Heddle's wire-format Pydantic models to JSON Schema.

Every cross-actor message is a ``WireEnvelope`` frame
(``heddle.core.envelope``) whose ``payload`` holds a typed *body*,
selected by ``payload_type``.  This script exports the frame schema
(``wire_envelope.schema.json``) and one self-contained schema per core
body — ``TaskMessage``, ``TaskResult``, ``OrchestratorGoal`` — plus the
standalone ``CheckpointState``.  Foreign-language SDKs (.NET, Swift, JVM) and
external integrations don't speak Pydantic; they need JSON Schema in a
stable on-disk location to feed into off-the-shelf code generators
(``quicktype``, ``NJsonSchema``, ``datamodel-code-generator``).

This script exports each model's ``.model_json_schema()`` to
``schemas/v1/<model>.schema.json`` with a stable sort order and trailing
newline so the output is git-diffable.  CI runs the script in ``--check``
mode and fails when the committed schemas drift from what the live
Pydantic models would produce — the same drift-prevention pattern that
``ruff format --check`` uses.

Usage:

    uv run python tools/export_schemas.py            # rewrite schemas/v1/
    uv run python tools/export_schemas.py --check    # CI: exit 1 on drift
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from heddle.core.envelope import WireEnvelope
from heddle.core.messages import (
    CheckpointState,
    OrchestratorGoal,
    TaskMessage,
    TaskResult,
)

# Each entry: (filename stem, Pydantic model class).  ``filename`` is the
# basename inside ``schemas/v1/``.
#
# Versioning (pre-1.0): ``v1`` names the current wire contract, not a
# frozen published artifact.  The wire-envelope reshape (S1-S4) changed
# these schemas in place under the clean-slate rule in
# ``heddle-workspace/anchors/AGENTIC-DEV.md``; the CHANGELOG marks the
# release as a breaking wire change.  After 1.0, a breaking field change
# moves to ``schemas/v2/`` instead of overwriting ``v1``.
#
# Only the frame and core bodies are exported. Contrib bodies are not part
# of the exported wire contract.
_EXPORTS: list[tuple[str, type]] = [
    ("wire_envelope", WireEnvelope),
    ("task_message", TaskMessage),
    ("task_result", TaskResult),
    ("orchestrator_goal", OrchestratorGoal),
    ("checkpoint_state", CheckpointState),
]

# Body model -> ``payload_type`` discriminator, recorded in each body
# schema as ``x-heddle-payload-type`` so SDKs can map discriminator to
# schema without a side table.  Must match the ``register_payload_type``
# calls in ``heddle.core.messages`` (asserted in tests).
_PAYLOAD_TYPES: dict[type, str] = {
    TaskMessage: "core.TaskMessage",
    TaskResult: "core.TaskResult",
    OrchestratorGoal: "core.OrchestratorGoal",
}

_OUTPUT_DIR = Path(__file__).resolve().parents[1] / "schemas" / "v1"

# Pydantic emits JSON Schema draft 2020-12 (``$defs``/``$ref``); state it so
# code generators that default to draft-07 or draft-04 don't guess.
_DIALECT = "https://json-schema.org/draft/2020-12/schema"


def _schema(model: type) -> dict[str, Any]:
    """Return the exported JSON Schema for ``model``.

    Adjustments over raw ``model_json_schema()``, so the exported contract
    states what the runtime actually enforces and how to read it:

    - Every schema: declare its dialect (``$schema``, draft 2020-12).
    - ``WireEnvelope``: Pydantic renders ``extra="allow"`` as
      ``additionalProperties: true``, but the frame's validator rejects any
      unknown key that is not ``_``-prefixed (Middleware Lane, DESIGN_INVARIANTS
      #22).  Export that as ``additionalProperties: false`` plus a ``^_``
      ``patternProperties`` carve-out.
    - Core bodies: annotate the ``payload_type`` that selects them.
    """
    schema: dict[str, Any] = {"$schema": _DIALECT, **model.model_json_schema()}
    if model is WireEnvelope:
        schema["additionalProperties"] = False
        schema["patternProperties"] = {"^_": {}}
    payload_type = _PAYLOAD_TYPES.get(model)
    if payload_type is not None:
        schema["x-heddle-payload-type"] = payload_type
    return schema


def _render(model: type) -> str:
    """Render a model's exported JSON Schema with stable sort + trailing newline."""
    return json.dumps(_schema(model), indent=2, sort_keys=True) + "\n"


def _write_all() -> list[Path]:
    """Write every export to disk.  Returns the list of paths written."""
    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for stem, model in _EXPORTS:
        path = _OUTPUT_DIR / f"{stem}.schema.json"
        path.write_text(_render(model), encoding="utf-8")
        written.append(path)
    return written


def _check_all() -> int:
    """Compare on-disk schemas against the live render.  Return shell exit code."""
    drift: list[str] = []
    for stem, model in _EXPORTS:
        path = _OUTPUT_DIR / f"{stem}.schema.json"
        expected = _render(model)
        actual = path.read_text(encoding="utf-8") if path.exists() else ""
        if expected != actual:
            drift.append(stem)
    # A schema file with no live model (e.g. left behind after a model was
    # removed) would still be vendored by downstream SDKs; treat it as drift.
    exported = {f"{stem}.schema.json" for stem, _ in _EXPORTS}
    drift.extend(
        f"{path.name} (stale: no model exports it; delete it)"
        for path in sorted(_OUTPUT_DIR.glob("*.schema.json"))
        if path.name not in exported
    )
    if drift:
        sys.stderr.write(
            "Schema drift detected for: "
            + ", ".join(drift)
            + "\nRun ``uv run python tools/export_schemas.py`` and commit the result.\n"
        )
        return 1
    return 0


def main() -> int:
    """CLI entry point — exports schemas, or in ``--check`` mode reports drift."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit non-zero if the on-disk schemas don't match the live Pydantic output.",
    )
    args = parser.parse_args()
    if args.check:
        return _check_all()
    written = _write_all()
    for path in written:
        sys.stdout.write(f"wrote {path.relative_to(Path.cwd())}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
