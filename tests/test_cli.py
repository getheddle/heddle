"""
Test CLI commands (unit tests, no infrastructure).

Tests the Click CLI from loom.cli.main using Click's CliRunner.
All async operations are mocked — no NATS or external services needed.

NOTE: Importing loom.cli.main triggers a global structlog.configure() call.
We save and restore the structlog config to prevent pollution of other tests.
"""

from unittest.mock import MagicMock, patch

import click
import pytest
import structlog
from click.testing import CliRunner

# Save structlog config before importing cli (which reconfigures it globally).
_saved_structlog_config = structlog.get_config()

from loom.cli.main import _load_processing_backend, cli  # noqa: E402

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

        _load_processing_backend("mypackage.backends.MyBackend", {})

    mock_class.assert_called_once_with()


# ---------------------------------------------------------------------------
# submit command — context parsing
# ---------------------------------------------------------------------------


def test_submit_parses_context_key_value(tmp_path):
    """submit with --context key=value parses into a context dict."""
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run") as mock_run:
        result = runner.invoke(
            cli,
            [
                "submit",
                "Process document",
                "--nats-url",
                "nats://localhost:4222",
                "--context",
                "file_ref=test.pdf",
                "--context",
                "lang=en",
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


def test_submit_bad_context_no_equals():
    """submit with context missing '=' raises a ClickException."""
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run"):
        result = runner.invoke(
            cli,
            [
                "submit",
                "Process document",
                "--context",
                "bad_context_no_equals",
            ],
        )

    assert result.exit_code != 0
    assert "key=value" in result.output


# ---------------------------------------------------------------------------
# processor command — missing processing_backend
# ---------------------------------------------------------------------------


def test_processor_missing_backend_raises(tmp_path):
    """processor command raises if config lacks processing_backend."""
    config_path = _write_yaml(
        tmp_path / "proc.yaml",
        "name: test_proc\ntier: local\nworker_kind: processor\n",
    )
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run"):
        result = runner.invoke(
            cli,
            [
                "processor",
                "--config",
                config_path,
                "--nats-url",
                "nats://localhost:4222",
            ],
        )

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


def test_orchestrator_help():
    """orchestrator --help shows help text without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["orchestrator", "--help"])
    assert result.exit_code == 0
    assert "Start the dynamic LLM-based orchestrator" in result.output


def test_scheduler_help():
    """scheduler --help shows help text without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["scheduler", "--help"])
    assert result.exit_code == 0
    assert "Start the time-driven scheduler" in result.output


def test_workshop_help():
    """workshop --help shows help text without errors."""
    runner = CliRunner()
    result = runner.invoke(cli, ["workshop", "--help"])
    assert result.exit_code == 0
    assert "Start the LLM Worker Workshop" in result.output


# ---------------------------------------------------------------------------
# worker command — full execution paths
# ---------------------------------------------------------------------------


def test_worker_loads_config_and_runs(tmp_path):
    """worker command reads YAML, builds backends, and starts the actor."""
    config_path = _write_yaml(
        tmp_path / "worker.yaml",
        "name: summarizer\ndefault_model_tier: local\nsystem_prompt: You are a summarizer.\n",
    )
    runner = CliRunner()

    with (
        patch.dict("os.environ", {"OLLAMA_URL": "http://localhost:11434"}, clear=False),
        patch("loom.cli.main.asyncio.run") as mock_run,
    ):
        result = runner.invoke(
            cli,
            [
                "worker",
                "--config",
                config_path,
                "--tier",
                "local",
                "--nats-url",
                "nats://localhost:4222",
            ],
            catch_exceptions=False,
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


def test_worker_tier_mismatch_warns(tmp_path):
    """worker logs warning when CLI --tier differs from config default_model_tier."""
    config_path = _write_yaml(
        tmp_path / "worker.yaml",
        "name: summarizer\ndefault_model_tier: local\nsystem_prompt: You are a summarizer.\n",
    )
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run"):
        result = runner.invoke(
            cli,
            [
                "worker",
                "--config",
                config_path,
                "--tier",
                "standard",
                "--nats-url",
                "nats://localhost:4222",
            ],
        )

    # Command still succeeds (warning doesn't block execution)
    assert result.exit_code == 0


def test_worker_no_backend_for_tier_warns(tmp_path):
    """worker warns when no backend is configured for the requested tier."""
    config_path = _write_yaml(
        tmp_path / "worker.yaml",
        "name: summarizer\nsystem_prompt: You are a summarizer.\n",
    )
    runner = CliRunner()

    # No env vars set, so no backends are configured
    with (
        patch("loom.cli.main.asyncio.run"),
        patch.dict("os.environ", {}, clear=False),
    ):
        # Remove env vars that could configure backends
        import os

        old_ollama = os.environ.pop("OLLAMA_URL", None)
        old_anthropic = os.environ.pop("ANTHROPIC_API_KEY", None)
        try:
            result = runner.invoke(
                cli,
                [
                    "worker",
                    "--config",
                    config_path,
                    "--tier",
                    "frontier",
                    "--nats-url",
                    "nats://localhost:4222",
                ],
            )
        finally:
            if old_ollama:
                os.environ["OLLAMA_URL"] = old_ollama
            if old_anthropic:
                os.environ["ANTHROPIC_API_KEY"] = old_anthropic

    assert result.exit_code == 0


def test_worker_with_anthropic_backend(tmp_path):
    """worker configures standard + frontier backends from ANTHROPIC_API_KEY."""
    config_path = _write_yaml(
        tmp_path / "worker.yaml",
        "name: summarizer\ndefault_model_tier: standard\nsystem_prompt: You are a summarizer.\n",
    )
    runner = CliRunner()

    import os

    old_ollama = os.environ.pop("OLLAMA_URL", None)
    old_anthropic = os.environ.get("ANTHROPIC_API_KEY")

    try:
        os.environ["ANTHROPIC_API_KEY"] = "test-key-123"
        with patch("loom.cli.main.asyncio.run") as mock_run:
            result = runner.invoke(
                cli,
                [
                    "worker",
                    "--config",
                    config_path,
                    "--tier",
                    "standard",
                    "--nats-url",
                    "nats://localhost:4222",
                ],
            )
    finally:
        if old_ollama:
            os.environ["OLLAMA_URL"] = old_ollama
        if old_anthropic:
            os.environ["ANTHROPIC_API_KEY"] = old_anthropic
        elif "ANTHROPIC_API_KEY" in os.environ:
            del os.environ["ANTHROPIC_API_KEY"]

    assert result.exit_code == 0
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# processor command — full execution paths
# ---------------------------------------------------------------------------


def test_processor_loads_backend_and_runs(tmp_path):
    """processor command loads backend dynamically and starts the actor."""
    config_path = _write_yaml(
        tmp_path / "proc.yaml",
        "name: doc_extractor\nworker_kind: processor\nprocessing_backend: os.path.join\n",
    )
    runner = CliRunner()

    mock_backend = MagicMock()
    with (
        patch("loom.cli.main._load_processing_backend", return_value=mock_backend),
        patch("loom.cli.main.asyncio.run") as mock_run,
    ):
        result = runner.invoke(
            cli,
            [
                "processor",
                "--config",
                config_path,
                "--nats-url",
                "nats://localhost:4222",
                "--tier",
                "local",
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# pipeline command
# ---------------------------------------------------------------------------


def test_pipeline_loads_config_and_runs(tmp_path):
    """pipeline command reads YAML and starts PipelineOrchestrator."""
    config_path = _write_yaml(
        tmp_path / "pipeline.yaml",
        "name: test_pipeline\npipeline_stages:\n  - name: stage1\n    worker_type: summarizer\n",
    )
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run") as mock_run:
        result = runner.invoke(
            cli,
            [
                "pipeline",
                "--config",
                config_path,
                "--nats-url",
                "nats://localhost:4222",
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# orchestrator command
# ---------------------------------------------------------------------------


def test_orchestrator_loads_config_and_runs(tmp_path):
    """orchestrator command reads YAML and starts OrchestratorActor."""
    config_path = _write_yaml(
        tmp_path / "orch.yaml",
        "name: test_orch\nsystem_prompt: You are helpful.\n",
    )
    runner = CliRunner()

    mock_actor = MagicMock()
    with (
        patch("loom.cli.main.asyncio.run") as mock_run,
        patch("loom.orchestrator.runner.OrchestratorActor", return_value=mock_actor),
    ):
        result = runner.invoke(
            cli,
            [
                "orchestrator",
                "--config",
                config_path,
                "--nats-url",
                "nats://localhost:4222",
                "--redis-url",
                "",
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


def test_orchestrator_with_redis_import_error(tmp_path):
    """orchestrator continues without checkpointing if redis extras not installed."""
    config_path = _write_yaml(
        tmp_path / "orch.yaml",
        "name: test_orch\nsystem_prompt: You are helpful.\n",
    )
    runner = CliRunner()

    mock_actor = MagicMock()

    # Simulate ImportError for redis store by removing it from sys.modules
    import sys

    saved = sys.modules.pop("loom.contrib.redis.store", "NOT_PRESENT")
    # Insert None to force ImportError on import
    sys.modules["loom.contrib.redis.store"] = None

    try:
        with (
            patch("loom.cli.main.asyncio.run") as mock_run,
            patch("loom.orchestrator.runner.OrchestratorActor", return_value=mock_actor),
        ):
            result = runner.invoke(
                cli,
                [
                    "orchestrator",
                    "--config",
                    config_path,
                    "--nats-url",
                    "nats://localhost:4222",
                    "--redis-url",
                    "redis://localhost:6379",
                ],
            )
    finally:
        del sys.modules["loom.contrib.redis.store"]
        if saved != "NOT_PRESENT":
            sys.modules["loom.contrib.redis.store"] = saved

    assert result.exit_code == 0
    mock_run.assert_called_once()


def test_orchestrator_with_redis_store(tmp_path):
    """orchestrator creates RedisCheckpointStore when redis is available."""
    config_path = _write_yaml(
        tmp_path / "orch.yaml",
        "name: test_orch\nsystem_prompt: You are helpful.\nmax_concurrent_goals: 2\n",
    )
    runner = CliRunner()

    mock_store = MagicMock()
    mock_actor = MagicMock()
    with (
        patch("loom.cli.main.asyncio.run") as mock_run,
        patch("loom.contrib.redis.store.RedisCheckpointStore", return_value=mock_store),
        patch("loom.orchestrator.runner.OrchestratorActor", return_value=mock_actor),
    ):
        result = runner.invoke(
            cli,
            [
                "orchestrator",
                "--config",
                config_path,
                "--nats-url",
                "nats://localhost:4222",
                "--redis-url",
                "redis://localhost:6379",
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# scheduler command
# ---------------------------------------------------------------------------


def test_scheduler_loads_config_and_runs(tmp_path):
    """scheduler command reads YAML, validates, and starts SchedulerActor."""
    config_path = _write_yaml(
        tmp_path / "sched.yaml",
        "name: test_scheduler\nschedules:\n  - name: job1\n"
        "    interval_seconds: 60\n    dispatch_type: goal\n"
        "    goal: Check status\n",
    )
    runner = CliRunner()

    mock_actor = MagicMock()
    with (
        patch("loom.cli.main.asyncio.run") as mock_run,
        patch("loom.scheduler.config.validate_scheduler_config", return_value=[]),
        patch("loom.scheduler.scheduler.SchedulerActor", return_value=mock_actor),
    ):
        result = runner.invoke(
            cli,
            [
                "scheduler",
                "--config",
                config_path,
                "--nats-url",
                "nats://localhost:4222",
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


def test_scheduler_config_validation_errors(tmp_path):
    """scheduler command fails with ClickException when config has errors."""
    config_path = _write_yaml(
        tmp_path / "sched.yaml",
        "name: bad_scheduler\n",
    )
    runner = CliRunner()

    with patch(
        "loom.scheduler.config.validate_scheduler_config",
        return_value=["Missing 'schedules' field", "Invalid cron expression"],
    ):
        result = runner.invoke(
            cli,
            [
                "scheduler",
                "--config",
                config_path,
                "--nats-url",
                "nats://localhost:4222",
            ],
        )

    assert result.exit_code != 0
    assert "error(s)" in result.output


# ---------------------------------------------------------------------------
# router command
# ---------------------------------------------------------------------------


def test_router_loads_config_and_runs(tmp_path):
    """router command creates NATSBus + TaskRouter and runs."""
    runner = CliRunner()

    mock_router = MagicMock()
    mock_router.run = MagicMock(return_value=None)
    mock_router.process_messages = MagicMock(return_value=None)

    with (
        patch("loom.cli.main.asyncio.run") as mock_run,
        patch("loom.bus.nats_adapter.NATSBus"),
        patch("loom.router.router.TaskRouter", return_value=mock_router),
    ):
        result = runner.invoke(
            cli,
            [
                "router",
                "--config",
                "configs/router_rules.yaml",
                "--nats-url",
                "nats://localhost:4222",
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


# ---------------------------------------------------------------------------
# submit command — async path
# ---------------------------------------------------------------------------


def test_submit_calls_asyncio_run(tmp_path):
    """submit command invokes asyncio.run with the _submit coroutine."""
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run") as mock_run:
        result = runner.invoke(
            cli,
            [
                "submit",
                "Test goal",
                "--nats-url",
                "nats://localhost:4222",
            ],
        )

    assert result.exit_code == 0
    mock_run.assert_called_once()


def test_submit_with_multiple_context_pairs():
    """submit with multiple --context pairs all get parsed."""
    runner = CliRunner()

    with patch("loom.cli.main.asyncio.run"):
        result = runner.invoke(
            cli,
            [
                "submit",
                "Multi context goal",
                "--nats-url",
                "nats://localhost:4222",
                "--context",
                "a=1",
                "--context",
                "b=2",
                "--context",
                "c=with=equals",
            ],
        )

    assert result.exit_code == 0


# ---------------------------------------------------------------------------
# mcp command
# ---------------------------------------------------------------------------


def test_mcp_stdio_transport(tmp_path):
    """mcp command with stdio transport calls run_stdio."""
    config_path = _write_yaml(
        tmp_path / "mcp.yaml",
        "name: test_mcp\nnats_url: nats://localhost:4222\ntools:\n  workers: []\n",
    )
    runner = CliRunner()

    mock_server = MagicMock()
    mock_gateway = MagicMock()
    mock_gateway.tool_registry = {"tool1": MagicMock()}
    mock_gateway.resources = None

    with (
        patch("loom.mcp.create_server", return_value=(mock_server, mock_gateway)),
        patch("loom.mcp.run_stdio") as mock_run_stdio,
    ):
        result = runner.invoke(
            cli,
            [
                "mcp",
                "--config",
                config_path,
                "--transport",
                "stdio",
            ],
        )

    assert result.exit_code == 0
    mock_run_stdio.assert_called_once_with(mock_server, mock_gateway)


def test_mcp_streamable_http_transport(tmp_path):
    """mcp command with streamable-http transport calls run_streamable_http."""
    config_path = _write_yaml(
        tmp_path / "mcp.yaml",
        "name: test_mcp\nnats_url: nats://localhost:4222\ntools:\n  workers: []\n",
    )
    runner = CliRunner()

    mock_server = MagicMock()
    mock_gateway = MagicMock()
    mock_gateway.tool_registry = {}
    mock_gateway.resources = MagicMock()  # resources enabled

    with (
        patch("loom.mcp.create_server", return_value=(mock_server, mock_gateway)),
        patch("loom.mcp.run_streamable_http") as mock_run_http,
    ):
        result = runner.invoke(
            cli,
            [
                "mcp",
                "--config",
                config_path,
                "--transport",
                "streamable-http",
                "--host",
                "0.0.0.0",
                "--port",
                "9000",
            ],
        )

    assert result.exit_code == 0
    mock_run_http.assert_called_once_with(mock_server, mock_gateway, host="0.0.0.0", port=9000)


# ---------------------------------------------------------------------------
# workshop command
# ---------------------------------------------------------------------------


def test_workshop_starts_uvicorn(tmp_path):
    """workshop command creates the app and starts uvicorn."""
    runner = CliRunner()

    mock_app = MagicMock()
    with (
        patch("loom.workshop.app.create_app", return_value=mock_app) as mock_create,
        patch("uvicorn.run") as mock_uvicorn,
    ):
        result = runner.invoke(
            cli,
            [
                "workshop",
                "--port",
                "9090",
                "--host",
                "0.0.0.0",
                "--configs-dir",
                "/tmp/configs",
                "--db-path",
                "/tmp/test.duckdb",
            ],
        )

    assert result.exit_code == 0
    mock_create.assert_called_once_with(
        configs_dir="/tmp/configs",
        db_path="/tmp/test.duckdb",
        nats_url=None,
    )
    mock_uvicorn.assert_called_once_with(mock_app, host="0.0.0.0", port=9090, log_level="info")


def test_workshop_with_nats_url(tmp_path):
    """workshop command passes nats_url to create_app when provided."""
    runner = CliRunner()

    mock_app = MagicMock()
    with (
        patch("loom.workshop.app.create_app", return_value=mock_app) as mock_create,
        patch("uvicorn.run"),
    ):
        result = runner.invoke(
            cli,
            [
                "workshop",
                "--nats-url",
                "nats://localhost:4222",
            ],
        )

    assert result.exit_code == 0
    mock_create.assert_called_once_with(
        configs_dir="configs/",
        db_path="~/.loom/workshop.duckdb",
        nats_url="nats://localhost:4222",
    )
