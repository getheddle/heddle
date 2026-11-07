"""Strict JSON text decoding for wire messages (I-JSON, RFC 7493).

The v1 wire contract requires message text to be I-JSON: object member names
are unique at every depth, and numbers are finite. Python's ``json`` module
accepts both violations silently (a repeated name keeps the *last* value;
``NaN`` and ``Infinity`` parse to floats), and other languages' parsers
disagree with it — some keep the first value, some reject. A message that two
receivers read differently is a correctness and security hazard (a repeated
``payload_type`` could route one way in Python and another way elsewhere), so
the rule is to reject it. See ``schemas/v1/fixtures/README.md``.

This module is a leaf (no heddle imports) so the bus can use it without a
core↔bus import cycle.
"""

from __future__ import annotations

import json
import math
from typing import Any


class WireJSONError(ValueError):
    """Message text is not I-JSON: a repeated member name or a non-finite number."""


def _unique_members(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise WireJSONError(f"repeated member name {key!r}")
        result[key] = value
    return result


def _reject_constant(name: str) -> Any:
    raise WireJSONError(f"non-finite number {name}")


def _finite_float(text: str) -> float:
    # `1e400` is valid JSON syntax but overflows to infinity.
    value = float(text)
    if math.isinf(value):
        raise WireJSONError(f"number {text} is outside the IEEE 754 double range")
    return value


def loads(data: bytes | bytearray | str) -> Any:
    """Decode wire message text, rejecting what I-JSON forbids.

    Raises:
        WireJSONError: a repeated member name in any object, ``NaN`` /
            ``Infinity`` / ``-Infinity``, or a number that overflows a double.
        json.JSONDecodeError: the text is not JSON at all.
        UnicodeDecodeError: bytes that are not UTF-8.

    All three are ``ValueError`` subclasses, so a caller that treats
    any ``ValueError`` as "malformed, skip" (Invariant 8) handles all three.
    """
    text = data.decode("utf-8") if isinstance(data, (bytes, bytearray)) else data
    return json.loads(
        text,
        object_pairs_hook=_unique_members,
        parse_constant=_reject_constant,
        parse_float=_finite_float,
    )
