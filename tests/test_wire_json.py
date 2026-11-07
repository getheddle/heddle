"""Strict wire-text decoding (``heddle.core.wire_json``, I-JSON / RFC 7493)."""

from __future__ import annotations

import json

import pytest

from heddle.core.wire_json import WireJSONError, loads


def test_accepts_ordinary_json_and_bytes() -> None:
    text = '{"a": 1, "b": [1.5, -2, null, true], "c": {"d": "é"}}'
    assert loads(text) == json.loads(text)
    assert loads(text.encode()) == json.loads(text)
    assert loads(bytearray(text.encode())) == json.loads(text)


def test_keeps_large_integers_exact() -> None:
    assert loads('{"n": 123456789012345678901234567890}') == {"n": 123456789012345678901234567890}


@pytest.mark.parametrize(
    "text",
    [
        '{"a": 1, "a": 2}',
        '{"payload_type": "core.TaskMessage", "payload_type": "events.Event"}',
        '{"outer": {"x": 1, "x": 1}}',
        '{"list": [{"k": 1, "k": 2}]}',
    ],
)
def test_rejects_repeated_member_names_at_any_depth(text: str) -> None:
    with pytest.raises(WireJSONError, match="repeated member name"):
        loads(text)


def test_same_name_in_sibling_objects_is_fine() -> None:
    assert loads('{"a": {"k": 1}, "b": {"k": 2}}') == {"a": {"k": 1}, "b": {"k": 2}}


@pytest.mark.parametrize(
    "text", ['{"x": NaN}', '{"x": Infinity}', '{"x": -Infinity}', '{"x": 1e400}']
)
def test_rejects_non_finite_numbers(text: str) -> None:
    with pytest.raises(WireJSONError):
        loads(text)


def test_deep_nesting_is_a_wire_error_not_a_recursion_error() -> None:
    with pytest.raises(WireJSONError, match="too deep"):
        loads("[" * 100_000 + "]" * 100_000)


def test_every_error_is_a_value_error() -> None:
    for text in ('{"a": 1, "a": 2}', "{not json", b"\xff"):
        with pytest.raises(ValueError):
            loads(text)
