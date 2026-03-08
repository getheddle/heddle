"""
Lightweight JSON Schema validation for I/O contracts.
We avoid jsonschema dependency — this covers the 90% case.
Add jsonschema to dependencies if you need full Draft 2020-12.
"""
from __future__ import annotations

from typing import Any


def validate_input(data: dict[str, Any], schema: dict) -> list[str]:
    return _validate(data, schema, "input")


def validate_output(data: dict[str, Any], schema: dict) -> list[str]:
    return _validate(data, schema, "output")


def _validate(data: Any, schema: dict, context: str) -> list[str]:
    """Basic schema validation. Returns list of error strings (empty = valid)."""
    errors = []

    if not schema:
        return errors

    expected_type = schema.get("type")
    if expected_type == "object" and not isinstance(data, dict):
        return [f"{context}: expected object, got {type(data).__name__}"]

    if expected_type == "object":
        # Check required fields
        for field in schema.get("required", []):
            if field not in data:
                errors.append(f"{context}: missing required field '{field}'")

        # Check property types (shallow)
        props = schema.get("properties", {})
        for field, field_schema in props.items():
            if field in data:
                field_type = field_schema.get("type")
                value = data[field]
                if field_type == "string" and not isinstance(value, str):
                    errors.append(f"{context}.{field}: expected string")
                elif field_type == "number" and not isinstance(value, (int, float)):
                    errors.append(f"{context}.{field}: expected number")
                elif field_type == "integer" and not isinstance(value, int):
                    errors.append(f"{context}.{field}: expected integer")
                elif field_type == "array" and not isinstance(value, list):
                    errors.append(f"{context}.{field}: expected array")
                elif field_type == "boolean" and not isinstance(value, bool):
                    errors.append(f"{context}.{field}: expected boolean")

    return errors
