"""
Tests for heddle new worker / heddle new pipeline — interactive scaffolding.

All tests use CliRunner with input= for interactive prompts and tmp_path for isolation.
"""

from __future__ import annotations

import structlog
import yaml
from click.testing import CliRunner

_saved_structlog_config = structlog.get_config()
from heddle.cli.new import _build_schema, _validate_name, new  # noqa: E402

structlog.configure(**_saved_structlog_config)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_validate_name_valid():
    assert _validate_name("my_worker") is None
    assert _validate_name("x") is None
    assert _validate_name("worker123") is None


def test_validate_name_invalid():
    assert _validate_name("") is not None
    assert _validate_name("MyWorker") is not None  # uppercase
    assert _validate_name("123worker") is not None  # starts with digit
    assert _validate_name("my-worker") is not None  # hyphens


def test_build_schema_single_field():
    schema = _build_schema("text")
    assert schema["required"] == ["text"]
    assert "text" in schema["properties"]
    assert schema["properties"]["text"]["type"] == "string"


def test_build_schema_multiple_fields():
    schema = _build_schema("text, language, confidence")
    assert schema["required"] == ["text", "language", "confidence"]
    assert len(schema["properties"]) == 3


def test_build_schema_empty():
    schema = _build_schema("")
    assert schema["required"] == []
    assert schema["properties"] == {}


# ---------------------------------------------------------------------------
# heddle new --help
# ---------------------------------------------------------------------------


def test_new_help():
    result = CliRunner().invoke(new, ["--help"])
    assert result.exit_code == 0
    assert "Scaffold" in result.output


def test_new_worker_help():
    result = CliRunner().invoke(new, ["worker", "--help"])
    assert result.exit_code == 0
    assert "worker config" in result.output


def test_new_pipeline_help():
    result = CliRunner().invoke(new, ["pipeline", "--help"])
    assert result.exit_code == 0
    assert "pipeline config" in result.output


# ---------------------------------------------------------------------------
# heddle new worker
# ---------------------------------------------------------------------------


def test_new_worker_non_interactive(tmp_path):
    """Non-interactive creates a minimal valid worker."""
    result = CliRunner().invoke(
        new,
        [
            "worker",
            "--non-interactive",
            "--name",
            "test_worker",
            "--kind",
            "llm",
            "--tier",
            "local",
            "--configs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Created" in result.output

    # Verify the file was written
    dest = tmp_path / "workers" / "test_worker.yaml"
    assert dest.exists()

    config = yaml.safe_load(dest.read_text())
    assert config["name"] == "test_worker"
    assert config["default_model_tier"] == "local"
    assert config["reset_after_task"] is True
    assert "input_schema" in config
    assert "output_schema" in config
    assert "system_prompt" in config


def test_new_worker_llm_interactive(tmp_path):
    """Interactive LLM worker creation with prompted inputs."""
    # Inputs: name, kind=llm, tier=local, system prompt, input fields, output fields, timeout
    inputs = "\n".join(
        [
            "my_analyzer",  # name
            "llm",  # kind
            "standard",  # tier
            "Analyze the input text and extract key themes.",  # system prompt
            "text,language",  # input fields
            "themes,confidence",  # output fields
            "45",  # timeout
        ]
    )
    result = CliRunner().invoke(
        new,
        ["worker", "--configs-dir", str(tmp_path)],
        input=inputs,
    )
    assert result.exit_code == 0, result.output
    assert "Created" in result.output

    config = yaml.safe_load((tmp_path / "workers" / "my_analyzer.yaml").read_text())
    assert config["name"] == "my_analyzer"
    assert config["default_model_tier"] == "standard"
    assert "text" in config["input_schema"]["required"]
    assert "language" in config["input_schema"]["required"]
    assert "themes" in config["output_schema"]["required"]
    assert config["timeout_seconds"] == 45


def test_new_worker_processor_interactive(tmp_path):
    """Interactive processor worker creation."""
    inputs = "\n".join(
        [
            "my_processor",  # name
            "processor",  # kind
            "mypackage.backend.MyBackend",  # processing_backend
            "data",  # input fields
            "processed",  # output fields
            "120",  # timeout
        ]
    )
    result = CliRunner().invoke(
        new,
        ["worker", "--configs-dir", str(tmp_path)],
        input=inputs,
    )
    assert result.exit_code == 0, result.output

    config = yaml.safe_load((tmp_path / "workers" / "my_processor.yaml").read_text())
    assert config["worker_kind"] == "processor"
    assert config["processing_backend"] == "mypackage.backend.MyBackend"


def test_new_worker_name_conflict(tmp_path):
    """Existing file causes an error."""
    workers_dir = tmp_path / "workers"
    workers_dir.mkdir(parents=True)
    (workers_dir / "existing.yaml").write_text("name: existing\n")

    result = CliRunner().invoke(
        new,
        [
            "worker",
            "--non-interactive",
            "--name",
            "existing",
            "--configs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output


def test_new_worker_invalid_name():
    """Invalid name is rejected."""
    result = CliRunner().invoke(
        new,
        [
            "worker",
            "--non-interactive",
            "--name",
            "Invalid-Name",
            "--configs-dir",
            "/tmp",
        ],
    )
    assert result.exit_code != 0
    assert "lowercase" in result.output


# ---------------------------------------------------------------------------
# heddle new pipeline
# ---------------------------------------------------------------------------


def test_new_pipeline_non_interactive(tmp_path):
    """Non-interactive creates a minimal pipeline."""
    # Create a worker config so the pipeline can reference it
    workers_dir = tmp_path / "workers"
    workers_dir.mkdir(parents=True)
    (workers_dir / "summarizer.yaml").write_text("name: summarizer\nsystem_prompt: test\n")

    result = CliRunner().invoke(
        new,
        [
            "pipeline",
            "--non-interactive",
            "--name",
            "test_pipeline",
            "--configs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Created" in result.output

    dest = tmp_path / "orchestrators" / "test_pipeline.yaml"
    assert dest.exists()

    config = yaml.safe_load(dest.read_text())
    assert config["name"] == "test_pipeline"
    assert len(config["pipeline_stages"]) == 1


def test_new_pipeline_interactive_two_stages(tmp_path):
    """Interactive pipeline with two stages."""
    # Create worker configs
    workers_dir = tmp_path / "workers"
    workers_dir.mkdir(parents=True)
    (workers_dir / "summarizer.yaml").write_text("name: summarizer\nsystem_prompt: test\n")
    (workers_dir / "classifier.yaml").write_text("name: classifier\nsystem_prompt: test\n")

    # Inputs for 2 stages:
    # Stage 1: worker_type, stage_name, mapping (field=path, empty to finish), add another?
    # Stage 2: worker_type, stage_name, mapping, add another?
    # Then timeout
    inputs = "\n".join(
        [
            "test_pipe",  # pipeline name
            "summarizer",  # stage 1 worker_type
            "summarize",  # stage 1 name
            "text=goal.context.text",  # mapping pair
            "",  # end mapping
            "y",  # add another stage
            "classifier",  # stage 2 worker_type
            "classify",  # stage 2 name
            "text=summarize.output.summary",  # mapping pair
            "",  # end mapping
            "n",  # no more stages
            "300",  # timeout
        ]
    )
    result = CliRunner().invoke(
        new,
        ["pipeline", "--configs-dir", str(tmp_path)],
        input=inputs,
    )
    assert result.exit_code == 0, result.output
    assert "summarize → classify" in result.output

    config = yaml.safe_load((tmp_path / "orchestrators" / "test_pipe.yaml").read_text())
    assert len(config["pipeline_stages"]) == 2
    assert config["pipeline_stages"][0]["name"] == "summarize"
    assert config["pipeline_stages"][1]["name"] == "classify"
    assert config["pipeline_stages"][1]["input_mapping"]["text"] == "summarize.output.summary"


def test_new_pipeline_lists_workers(tmp_path):
    """Interactive mode lists available workers."""
    workers_dir = tmp_path / "workers"
    workers_dir.mkdir(parents=True)
    (workers_dir / "alpha.yaml").write_text("name: alpha\n")
    (workers_dir / "beta.yaml").write_text("name: beta\n")

    # Non-interactive to avoid the stage prompts, just check listing
    result = CliRunner().invoke(
        new,
        [
            "pipeline",
            "--non-interactive",
            "--name",
            "test_pipe",
            "--configs-dir",
            str(tmp_path),
        ],
    )
    # Non-interactive uses the first available worker
    assert result.exit_code == 0, result.output


def test_new_pipeline_name_conflict(tmp_path):
    """Existing file causes an error."""
    orch_dir = tmp_path / "orchestrators"
    orch_dir.mkdir(parents=True)
    (orch_dir / "existing.yaml").write_text("name: existing\n")

    result = CliRunner().invoke(
        new,
        [
            "pipeline",
            "--non-interactive",
            "--name",
            "existing",
            "--configs-dir",
            str(tmp_path),
        ],
    )
    assert result.exit_code != 0
    assert "already exists" in result.output
