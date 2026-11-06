"""Wire conformance fixtures (``schemas/v1/fixtures/``) agree with the runtime.

The fixtures are the language-neutral half of the wire contract: SDKs in
other languages run their serializers and validators against these exact
files (heddle-sdk#5).  This module proves, for every fixture, that the
committed JSON Schemas and the Python runtime (``heddle.core.envelope.parse``)
reach the same verdict at the same layer, and that valid fixtures
round-trip through the runtime losslessly.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

import heddle.core.messages  # noqa: F401 — registers core payload types
from heddle.core.envelope import WireEnvelope, get_payload_model, parse

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas" / "v1"
FIXTURES = SCHEMAS / "fixtures"
MANIFEST: dict[str, Any] = json.loads((FIXTURES / "manifest.json").read_text(encoding="utf-8"))
ENTRIES: list[dict[str, Any]] = MANIFEST["fixtures"]


def _validator(schema_file: str) -> Draft202012Validator:
    schema = json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))
    return Draft202012Validator(schema, format_checker=FormatChecker())


FRAME = _validator(MANIFEST["frame_schema"])
BODIES = {pt: _validator(f) for pt, f in MANIFEST["payload_types"].items()}


def _load(entry: dict[str, Any]) -> dict[str, Any]:
    return json.loads((FIXTURES / entry["file"]).read_text(encoding="utf-8"))


def _ids(entries: list[dict[str, Any]]) -> list[str]:
    return [e["file"] for e in entries]


VALID = [e for e in ENTRIES if e["expect"] == "valid"]
INVALID = [e for e in ENTRIES if e["expect"] == "invalid"]


def test_manifest_lists_every_fixture_file_exactly_once() -> None:
    on_disk = {p.relative_to(FIXTURES).as_posix() for p in FIXTURES.glob("*/*.json")}
    listed = [e["file"] for e in ENTRIES]
    assert len(listed) == len(set(listed))
    assert set(listed) == on_disk


def test_manifest_payload_types_match_runtime_registry_and_schemas() -> None:
    for payload_type, schema_file in MANIFEST["payload_types"].items():
        model = get_payload_model(payload_type)
        schema = json.loads((SCHEMAS / schema_file).read_text(encoding="utf-8"))
        assert schema["title"] == model.__name__
        assert schema["x-heddle-payload-type"] == payload_type


def test_date_time_format_is_enforced() -> None:
    """Guard: without an RFC 3339 checker, ``format: date-time`` is a no-op."""
    assert not FormatChecker().conforms("not-a-date", "date-time")


@pytest.mark.parametrize("entry", VALID, ids=_ids(VALID))
def test_valid_fixture_passes_schemas_and_runtime(entry: dict[str, Any]) -> None:
    data = _load(entry)
    assert data["payload_type"] == entry["payload_type"]
    FRAME.validate(data)
    BODIES[entry["payload_type"]].validate(data["payload"])

    envelope, body = parse(data)
    assert isinstance(body, get_payload_model(entry["payload_type"]))
    # Lossless round-trip: the frame (including Middleware-Lane `_` keys)
    # and the typed body both re-serialize to exactly the fixture.
    assert envelope.model_dump(mode="json") == data
    assert body.model_dump(mode="json") == data["payload"]


@pytest.mark.parametrize("entry", INVALID, ids=_ids(INVALID))
def test_invalid_fixture_rejected_at_stated_layer(entry: dict[str, Any]) -> None:
    data = _load(entry)
    layer = entry["rejected_at"]
    frame_ok = FRAME.is_valid(data)

    if layer == "frame":
        assert not frame_ok
        with pytest.raises(ValidationError):
            WireEnvelope.model_validate(data)
        return

    assert frame_ok
    WireEnvelope.model_validate(data)  # frame passes in the runtime too
    if layer == "body":
        assert not BODIES[entry["payload_type"]].is_valid(data["payload"])
        with pytest.raises(ValidationError):
            parse(data)
    elif layer == "dispatch":
        assert entry["payload_type"] not in BODIES
        with pytest.raises(KeyError):
            parse(data)
    else:  # pragma: no cover — manifest typo
        pytest.fail(f"unknown rejected_at layer {layer!r}")
