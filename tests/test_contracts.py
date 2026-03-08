"""Test I/O contract validation."""
from loom.core.contracts import validate_input, validate_output


def test_missing_required_field():
    schema = {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}
    errors = validate_input({}, schema)
    assert any("missing required" in e for e in errors)


def test_valid_input():
    schema = {"type": "object", "required": ["text"], "properties": {"text": {"type": "string"}}}
    errors = validate_input({"text": "hello"}, schema)
    assert errors == []


def test_wrong_type():
    schema = {"type": "object", "properties": {"count": {"type": "integer"}}}
    errors = validate_input({"count": "not_a_number"}, schema)
    assert any("expected integer" in e for e in errors)


def test_empty_schema():
    errors = validate_input({"anything": "goes"}, {})
    assert errors == []


def test_multiple_required_fields():
    schema = {
        "type": "object",
        "required": ["text", "categories"],
        "properties": {
            "text": {"type": "string"},
            "categories": {"type": "array"},
        },
    }
    errors = validate_input({}, schema)
    assert len(errors) == 2


def test_valid_output():
    schema = {
        "type": "object",
        "required": ["summary", "key_points"],
        "properties": {
            "summary": {"type": "string"},
            "key_points": {"type": "array"},
        },
    }
    errors = validate_output({"summary": "test", "key_points": ["a"]}, schema)
    assert errors == []


def test_not_an_object():
    schema = {"type": "object"}
    errors = validate_input("not a dict", schema)
    assert any("expected object" in e for e in errors)


def test_boolean_type_check():
    schema = {"type": "object", "properties": {"flag": {"type": "boolean"}}}
    errors = validate_input({"flag": "true"}, schema)
    assert any("expected boolean" in e for e in errors)

    errors = validate_input({"flag": True}, schema)
    assert errors == []


def test_number_type_check():
    schema = {"type": "object", "properties": {"score": {"type": "number"}}}
    errors = validate_input({"score": 0.95}, schema)
    assert errors == []

    errors = validate_input({"score": 5}, schema)
    assert errors == []

    errors = validate_input({"score": "high"}, schema)
    assert any("expected number" in e for e in errors)
