"""
Test CLI commands (unit tests, no infrastructure).

Tests the Click CLI from loom.cli.main using Click's CliRunner.
All async operations are mocked — no NATS or external services needed.

NOTE: Importing loom.cli.main triggers a global structlog.configure() call.
We save and restore the structlog config to prevent pollution of other tests.
"""
import os
from unittest.mock import MagicMock, patch

import click
import pytest
import structlog
from click.testing import CliRunner

# Save structlog config before importing cli (which reconfigures it globally).
_saved_structlog_config = structlog.get_config()

from loom.cli.main import cli, _load_processing_backend  # noqa: E402

# Restore structlog config immediately after import.
structlog.configure(**_saved_structlog_config)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_yaml(path, content: str) -> str:
    """Write YAML content to a file and return the path as a string."""
    path.write_text(content)
    return str(path)


# ---------------------------------------------------------------------------
# _load_processing_backend — dotted path resolution
# ---------------------------------------------------------------------------


def test_load_backend_no_dot_raises():
    """A name without a dot is rejected with a ClickException."""
    with pytest.raises(click.ClickException, match="must be a fully qualified class path"):
        _load_processing_backend("NoDotName", {})


def test_load_backend_bad_module_raises():
    """An unimportable module path raises a ClickException."""
    with pytest.raises(click.ClickException, match="Cannot import backend module"):
        _load_processing_backend("totally.nonexistent.module.Backend", {})


def test_load_backend_bad_class_raises():
    """A valid module with a missing class raises a ClickException."""
    # os is a valid module but has no class called 'NoSuchClass'
    with pytest.raises(click.ClickException, match="Backend class 'NoSuchClass' not found"):
        _load_processing_backend("os.path.NoSuchClass", {})


def test_load_backend_valid_dotted_path():
    """A valid dotted path imports and instantiates the class."""
    # Use a known stdlib class as the backend — MagicMock is callable
    mock_class = MagicMock(return_value="instance")
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MyBackend = mock_class
        mock_import.return_value = mock_module

        result = _load_processing_backend("mypackage.backends.MyBackend", {})

    mock_import.assert_called_once_with("mypackage.backends")
    mock_class.assert_called_once_with()
    assert result == "instance"


def test_load_backend_passes_backend_config_as_kwargs():
    """backend_config from the worker config is passed as kwargs to the class."""
    mock_class = MagicMock(return_value="configured_instance")
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MyBackend = mock_class
        mock_import.return_value = mock_module

        config = {"backend_config": {"db_path": "/tmp/test.db", "timeout": 30}}
        result = _load_processing_backend("mypackage.backends.MyBackend", config)

    mock_class.assert_called_once_with(db_path="/tmp/test.db", timeout=30)
    assert result == "configured_instance"


def test_load_backend_no_backend_config_passes_empty():
    """Without backend_config in the worker config, empty kwargs are passed."""
    mock_class = MagicMock(return_value="default_instance")
    with patch("importlib.import_module") as mock_import:
        mock_module = MagicMock()
        mock_module.MyBackend = mock_class
        mock_import.return_value = mock_module

        result = _load_processing_backend("mypackage.backends.MyBackend", {})

    mock_class.assert_called_once_with()


# ---------------------------------------------------------------------------
# submit command — context parsing
# ---------------------------------------------------------------------------


def test_submit_parses_context_key_value(tmp_path):
    """submit with --context key=value parses into a context dict."""
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run") as mock_run:
        result = runner.invoke(cli, [
            "submit", "Process document",
            "--nats-url", "nats://localhost:4222",
            "--context", "file_ref=test.pdf",
            "--context", "lang=en",
        ])

    assert result.exit_code == 0
    mock_run.assert_called_once()


def test_submit_bad_context_no_equals():
    """submit with context missing '=' raises a ClickException."""
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run"):
        result = runner.invoke(cli, [
            "submit", "Process document",
            "--context", "bad_context_no_equals",
        ])

    assert result.exit_code != 0
    assert "key=value" in result.output


# ---------------------------------------------------------------------------
# processor command — missing processing_backend
# ---------------------------------------------------------------------------


def test_processor_missing_backend_raises(tmp_path):
    """processor command raises if config lacks processing_backend."""
    config_path = _write_yaml(
        tmp_path / "proc.yaml",
        "name: test_proc\ntier: local\n",
    )
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run"):
        result = runner.invoke(cli, [
            "processor",
            "--config", config_path,
            "--nats-url", "nats://localhost:4222",
        ])

    assert result.exit_code != 0
    assert "processing_backend" in result.output


# ---------------------------------------------------------------------------
# help text smoke tests
# ---------------------------------------------------------------------------


def test_worker_help():
    """worker --help shows help text without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["worker", "--help"])
    assert result.exit_code == 0
    assert "Start an LLM worker actor" in result.output


def test_router_help():
    """router --help shows help text without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["router", "--help"])
    assert result.exit_code == 0
    assert "Start the deterministic task router" in result.output


def test_mcp_help():
    """mcp --help shows help text without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["mcp", "--help"])
    assert result.exit_code == 0
    assert "Start an MCP server" in result.output


def test_pipeline_help():
    """pipeline --help shows help text without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["pipeline", "--help"])
    assert result.exit_code == 0
    assert "Start a pipeline orchestrator" in result.output


def test_submit_help():
    """submit --help shows help text without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["submit", "--help"])
    assert result.exit_code == 0
    assert "Submit a goal" in result.output
