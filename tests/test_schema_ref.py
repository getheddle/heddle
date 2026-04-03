"""Tests for schema_ref resolution (input_schema_ref / output_schema_ref)."""

from __future__ import annotations

import textwrap

import pytest
from pydantic import BaseModel

from heddle.core.config import ConfigValidationError, load_config, resolve_schema_refs

# ---------------------------------------------------------------------------
# A minimal Pydantic model used by the tests (importable from this module)
# ---------------------------------------------------------------------------


class SampleInput(BaseModel):
    text: str
    count: int = 0


class SampleOutput(BaseModel):
    result: str
    score: float


class NotAModel:
    """Plain class — not a Pydantic BaseModel."""

    pass


# ---------------------------------------------------------------------------
# resolve_schema_refs — unit tests
# ---------------------------------------------------------------------------


class TestResolveSchemaRefs:
    def test_input_schema_ref_resolved(self):
        config: dict = {"input_schema_ref": "tests.test_schema_ref.SampleInput"}
        resolve_schema_refs(config)
        schema = config["input_schema"]
        assert schema["type"] == "object"
        assert "text" in schema["properties"]
        assert "count" in schema["properties"]
        assert "text" in schema["required"]

    def test_output_schema_ref_resolved(self):
        config: dict = {"output_schema_ref": "tests.test_schema_ref.SampleOutput"}
        resolve_schema_refs(config)
        schema = config["output_schema"]
        assert schema["type"] == "object"
        assert "result" in schema["properties"]
        assert "score" in schema["properties"]

    def test_inline_schema_takes_precedence(self):
        inline = {"type": "object", "properties": {"x": {"type": "string"}}}
        config: dict = {
            "input_schema": inline,
            "input_schema_ref": "tests.test_schema_ref.SampleInput",
        }
        resolve_schema_refs(config)
        # The inline schema must win — ref is ignored.
        assert config["input_schema"] is inline

    def test_no_ref_keys_is_noop(self):
        config: dict = {"name": "worker", "input_schema": {"type": "object"}}
        original = dict(config)
        resolve_schema_refs(config)
        assert config == original

    def test_bad_module_path_raises(self):
        config: dict = {"input_schema_ref": "nonexistent.module.Model"}
        with pytest.raises(ConfigValidationError, match="cannot import module"):
            resolve_schema_refs(config)

    def test_bad_class_name_raises(self):
        config: dict = {"input_schema_ref": "tests.test_schema_ref.NoSuchClass"}
        with pytest.raises(ConfigValidationError, match="has no attribute"):
            resolve_schema_refs(config)

    def test_not_pydantic_model_raises(self):
        config: dict = {"input_schema_ref": "tests.test_schema_ref.NotAModel"}
        with pytest.raises(ConfigValidationError, match="not a Pydantic BaseModel"):
            resolve_schema_refs(config)

    def test_single_segment_path_raises(self):
        config: dict = {"input_schema_ref": "JustAClassName"}
        with pytest.raises(ConfigValidationError, match="fully qualified"):
            resolve_schema_refs(config)

    def test_both_refs_resolved(self):
        config: dict = {
            "input_schema_ref": "tests.test_schema_ref.SampleInput",
            "output_schema_ref": "tests.test_schema_ref.SampleOutput",
        }
        resolve_schema_refs(config)
        assert "text" in config["input_schema"]["properties"]
        assert "score" in config["output_schema"]["properties"]

    def test_pipeline_stage_refs_resolved(self):
        config: dict = {
            "name": "test_pipeline",
            "pipeline_stages": [
                {
                    "name": "stage_a",
                    "worker_type": "sample",
                    "input_schema_ref": "tests.test_schema_ref.SampleInput",
                    "output_schema_ref": "tests.test_schema_ref.SampleOutput",
                },
                {
                    "name": "stage_b",
                    "worker_type": "other",
                    # No refs — should be untouched.
                },
            ],
        }
        resolve_schema_refs(config)
        stage_a = config["pipeline_stages"][0]
        assert "text" in stage_a["input_schema"]["properties"]
        assert "score" in stage_a["output_schema"]["properties"]
        # stage_b should not have schemas injected.
        stage_b = config["pipeline_stages"][1]
        assert "input_schema" not in stage_b

    def test_returns_config_for_chaining(self):
        config: dict = {"input_schema_ref": "tests.test_schema_ref.SampleInput"}
        result = resolve_schema_refs(config)
        assert result is config


# ---------------------------------------------------------------------------
# load_config with resolve_refs
# ---------------------------------------------------------------------------


class TestLoadConfigWithRefs:
    def test_load_config_resolves_refs_by_default(self, tmp_path):
        p = tmp_path / "worker.yaml"
        p.write_text(
            textwrap.dedent("""\
                name: test_worker
                system_prompt: do stuff
                input_schema_ref: tests.test_schema_ref.SampleInput
            """)
        )
        config = load_config(p)
        assert "input_schema" in config
        assert config["input_schema"]["type"] == "object"

    def test_load_config_skip_refs(self, tmp_path):
        p = tmp_path / "worker.yaml"
        p.write_text(
            textwrap.dedent("""\
                name: test_worker
                system_prompt: do stuff
                input_schema_ref: tests.test_schema_ref.SampleInput
            """)
        )
        config = load_config(p, resolve_refs=False)
        assert "input_schema" not in config
        assert config["input_schema_ref"] == "tests.test_schema_ref.SampleInput"
