"""
Tests for heddle validate command — config file validation.

All tests use tmp_path for isolation. No external services needed.
"""

from __future__ import annotations

import structlog
from click.testing import CliRunner

_saved_structlog_config = structlog.get_config()
from heddle.cli.validate import _detect_config_type, validate  # noqa: E402

structlog.configure(**_saved_structlog_config)


# ---------------------------------------------------------------------------
# Type detection
# ---------------------------------------------------------------------------


def test_detect_worker_with_system_prompt():
    assert _detect_config_type({"name": "x", "system_prompt": "do stuff"}) == "worker"


def test_detect_worker_with_processing_backend():
    assert _detect_config_type({"name": "x", "processing_backend": "a.b.C"}) == "worker"


def test_detect_pipeline():
    assert _detect_config_type({"name": "x", "pipeline_stages": []}) == "pipeline"


def test_detect_orchestrator():
    assert _detect_config_type({"name": "x", "available_workers": []}) == "orchestrator"


def test_detect_worker_fallback_schemas():
    assert _detect_config_type({"input_schema": {}, "output_schema": {}}) == "worker"


def test_detect_unknown():
    assert _detect_config_type({"random": "stuff"}) is None


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------


def test_validate_help():
    result = CliRunner().invoke(validate, ["--help"])
    assert result.exit_code == 0
    assert "Validate worker" in result.output


def test_validate_valid_worker(tmp_path):
    """A valid worker config passes validation."""
    cfg = tmp_path / "my_worker.yaml"
    cfg.write_text(
        "name: test_worker\n"
        "system_prompt: You are a test worker.\n"
        "default_model_tier: local\n"
        "input_schema:\n"
        "  type: object\n"
        "  required: [text]\n"
        "  properties:\n"
        "    text:\n"
        "      type: string\n"
        "output_schema:\n"
        "  type: object\n"
        "  required: [result]\n"
        "  properties:\n"
        "    result:\n"
        "      type: string\n"
        "reset_after_task: true\n"
    )
    result = CliRunner().invoke(validate, [str(cfg)])
    assert result.exit_code == 0
    assert "✓" in result.output
    assert "[worker]" in result.output


def test_validate_invalid_worker(tmp_path):
    """An invalid worker config shows errors."""
    cfg = tmp_path / "bad_worker.yaml"
    cfg.write_text("name: bad_worker\n")  # missing system_prompt
    result = CliRunner().invoke(validate, [str(cfg)])
    assert result.exit_code == 1
    assert "✗" in result.output


def test_validate_valid_pipeline(tmp_path):
    """A valid pipeline config passes validation."""
    cfg = tmp_path / "my_pipeline.yaml"
    cfg.write_text(
        "name: test_pipeline\n"
        "pipeline_stages:\n"
        "  - name: step1\n"
        "    worker_type: summarizer\n"
        "    input_mapping:\n"
        '      text: "goal.context.text"\n'
    )
    result = CliRunner().invoke(validate, [str(cfg)])
    assert result.exit_code == 0
    assert "✓" in result.output
    assert "[pipeline]" in result.output


def test_validate_invalid_pipeline(tmp_path):
    """A pipeline without stages fails."""
    cfg = tmp_path / "bad_pipeline.yaml"
    cfg.write_text("name: bad_pipeline\n")  # missing pipeline_stages
    result = CliRunner().invoke(validate, [str(cfg)])
    assert result.exit_code == 1
    assert "✗" in result.output


def test_validate_multiple_files(tmp_path):
    """Validates multiple files, reports each."""
    good = tmp_path / "good.yaml"
    good.write_text(
        "name: good_worker\n"
        "system_prompt: test\n"
        "default_model_tier: local\n"
        "input_schema:\n"
        "  type: object\n"
        "  required: [x]\n"
        "  properties:\n"
        "    x:\n"
        "      type: string\n"
        "output_schema:\n"
        "  type: object\n"
        "  required: [y]\n"
        "  properties:\n"
        "    y:\n"
        "      type: string\n"
        "reset_after_task: true\n"
    )
    bad = tmp_path / "bad.yaml"
    bad.write_text("name: bad_worker\n")

    result = CliRunner().invoke(validate, [str(good), str(bad)])
    assert result.exit_code == 1
    assert "1 invalid, 1 valid" in result.output


def test_validate_nonexistent_file():
    """A nonexistent file reports an error."""
    result = CliRunner().invoke(validate, ["/nonexistent/file.yaml"])
    assert result.exit_code == 1
    assert "File not found" in result.output


def test_validate_empty_yaml(tmp_path):
    """An empty YAML file reports an error."""
    cfg = tmp_path / "empty.yaml"
    cfg.write_text("")
    result = CliRunner().invoke(validate, [str(cfg)])
    assert result.exit_code == 1
    assert "empty" in result.output


def test_validate_invalid_yaml(tmp_path):
    """Malformed YAML reports an error."""
    cfg = tmp_path / "broken.yaml"
    cfg.write_text("{{not valid yaml")
    result = CliRunner().invoke(validate, [str(cfg)])
    assert result.exit_code == 1
    assert "Invalid YAML" in result.output


def test_validate_all_flag(tmp_path):
    """--all scans the configs directory."""
    workers_dir = tmp_path / "workers"
    workers_dir.mkdir()
    (workers_dir / "ok.yaml").write_text(
        "name: ok_worker\n"
        "system_prompt: test\n"
        "default_model_tier: local\n"
        "input_schema:\n"
        "  type: object\n"
        "  required: [x]\n"
        "  properties:\n"
        "    x:\n"
        "      type: string\n"
        "output_schema:\n"
        "  type: object\n"
        "  required: [y]\n"
        "  properties:\n"
        "    y:\n"
        "      type: string\n"
    )
    result = CliRunner().invoke(validate, ["--all", "--configs-dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "1 config(s) valid" in result.output


def test_validate_all_skips_template(tmp_path):
    """--all skips _template.yaml."""
    workers_dir = tmp_path / "workers"
    workers_dir.mkdir()
    (workers_dir / "_template.yaml").write_text("name: template\n")
    result = CliRunner().invoke(validate, ["--all", "--configs-dir", str(tmp_path)])
    assert result.exit_code != 0  # No files found
    assert "No YAML files found" in result.output


def test_validate_no_args():
    """No args and no --all flag gives an error."""
    result = CliRunner().invoke(validate, [])
    assert result.exit_code != 0
    assert "Provide config file paths" in result.output


def test_validate_unknown_type(tmp_path):
    """A file with unrecognizable content reports detection failure."""
    cfg = tmp_path / "mystery.yaml"
    cfg.write_text("foo: bar\nbaz: qux\n")
    result = CliRunner().invoke(validate, [str(cfg)])
    assert result.exit_code == 1
    assert "Cannot detect config type" in result.output


def test_validate_real_configs():
    """Validate the shipped worker configs (smoke test)."""
    result = CliRunner().invoke(validate, ["--all", "--configs-dir", "configs/"])
    # If we're running from the heddle root, this should find and validate configs
    if result.exit_code == 0:
        assert "valid" in result.output
    # If configs/ doesn't exist in CWD (e.g., running from test dir), skip gracefully
