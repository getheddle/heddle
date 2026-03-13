"""
Loom CLI -- entry point for running all Loom components.

This module provides the Click-based command-line interface for launching
every type of Loom actor. Each command starts a long-running async process
that connects to NATS and processes messages until terminated.

Commands:
    loom worker       -- Start an LLM worker (requires OLLAMA_URL or ANTHROPIC_API_KEY)
    loom processor    -- Start a non-LLM processor worker (e.g., DoclingBackend)
    loom pipeline     -- Start a pipeline orchestrator (sequential stage execution)
    loom orchestrator -- Start the dynamic LLM-based orchestrator (OrchestratorActor)
    loom scheduler    -- Start the time-driven scheduler (cron + interval dispatch)
    loom router       -- Start the deterministic task router
    loom submit       -- Submit a goal to the orchestrator

Typical local dev startup (5 terminals):
    1. docker run -p 4222:4222 nats:latest
    2. loom router --config configs/router_rules.yaml --nats-url nats://localhost:4222
    3. loom processor --config configs/workers/doc_extractor.yaml --nats-url nats://localhost:4222
    4. loom worker --config configs/workers/doc_classifier.yaml --tier local --nats-url nats://localhost:4222
    5. loom submit "Process document" --context file_ref=test.pdf --nats-url nats://localhost:4222

Architecture notes:
    - Workers are stateless: one task in, one result out, state reset.
    - The router is deterministic (no LLM) -- it routes by worker_type and model_tier.
    - All inter-actor messages are typed Pydantic models (see loom.core.messages).
    - NATS subjects follow the convention: loom.tasks.{worker_type}.{tier}
    - Workers subscribe with queue groups for horizontal scaling.
"""

import asyncio
import importlib

import click
import structlog

# Configure structlog for human-readable console output with ISO timestamps.
# This runs at import time so all CLI commands share the same log format.
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)

logger = structlog.get_logger()


@click.group()
def cli():
    """Loom -- Lightweight Orchestrated Operational Mesh."""
    pass


# ---------------------------------------------------------------------------
# worker command
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--config", required=True, help="Path to worker config YAML")
@click.option("--nats-url", default="nats://nats:4222", help="NATS server URL")
@click.option("--tier", default="standard", help="Model tier this worker serves")
def worker(config: str, nats_url: str, tier: str):
    """Start an LLM worker actor.

    Loads a worker configuration YAML and starts a long-running LLM worker
    that subscribes to its NATS subject and processes tasks.

    LLM backends are resolved from environment variables:

    \b
        OLLAMA_URL        -> OllamaBackend  (serves "local" tier)
        OLLAMA_MODEL      -> Override Ollama model (default: llama3.2:3b)
        ANTHROPIC_API_KEY -> AnthropicBackend (serves "standard" and "frontier")
        FRONTIER_MODEL    -> Override frontier model (default: claude-opus-4-20250514)

    The worker subscribes to: loom.tasks.{worker_name}.{tier}
    with queue group: workers-{worker_name} (enables horizontal scaling).

    If --tier does not match the config's default_model_tier, a warning is
    logged but execution continues (the CLI tier takes precedence).
    """
    import os

    import yaml

    from loom.worker.backends import AnthropicBackend, OllamaBackend
    from loom.worker.runner import LLMWorker

    with open(config) as f:
        cfg = yaml.safe_load(f)

    # Warn if the CLI --tier diverges from the config's declared default.
    # This catches mistakes like starting a "local"-only worker with --tier standard.
    # Execution is not blocked because the operator may intentionally override the tier.
    config_default_tier = cfg.get("default_model_tier")
    if config_default_tier and tier != config_default_tier:
        logger.warning(
            "worker.tier_mismatch",
            cli_tier=tier,
            config_default_tier=config_default_tier,
            config_path=config,
            hint=(
                f"Config '{config}' declares default_model_tier='{config_default_tier}' "
                f"but worker is starting with --tier='{tier}'. "
                f"Ensure a backend for the '{tier}' tier is configured."
            ),
        )

    # Build backends from environment variables.
    # Only tiers with configured backends can actually serve requests.
    # If a backend for the requested --tier is not available, the worker will
    # start but fail when it tries to process a task for that tier.
    backends = {}
    if os.getenv("OLLAMA_URL"):
        ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        backends["local"] = OllamaBackend(
            model=ollama_model, base_url=os.getenv("OLLAMA_URL")
        )
    if os.getenv("ANTHROPIC_API_KEY"):
        backends["standard"] = AnthropicBackend(api_key=os.getenv("ANTHROPIC_API_KEY"))
        backends["frontier"] = AnthropicBackend(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=os.getenv("FRONTIER_MODEL", "claude-opus-4-20250514"),
        )

    # Warn if no backend is available for the requested tier.
    if tier not in backends:
        logger.warning(
            "worker.no_backend_for_tier",
            tier=tier,
            available_tiers=list(backends.keys()),
            hint=(
                f"No backend configured for tier '{tier}'. "
                f"Set OLLAMA_URL (for 'local') or ANTHROPIC_API_KEY "
                f"(for 'standard'/'frontier') in your environment."
            ),
        )

    actor = LLMWorker(
        actor_id=f"worker-{cfg['name']}-{tier}",
        config_path=config,
        backends=backends,
        nats_url=nats_url,
    )
    subject = f"loom.tasks.{cfg['name']}.{tier}"
    asyncio.run(actor.run(subject, queue_group=f"workers-{cfg['name']}"))


# ---------------------------------------------------------------------------
# processor command
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--config", required=True, help="Path to processor worker config YAML")
@click.option("--nats-url", default="nats://nats:4222", help="NATS server URL")
@click.option("--tier", default="local", help="Tier this processor serves")
def processor(config: str, nats_url: str, tier: str):
    """Start a processor (non-LLM) worker actor.

    Processors handle tasks that do not require an LLM, such as document
    extraction, format conversion, or data transformation. The processing
    backend is loaded dynamically by fully qualified class path from the
    worker config YAML.

    This keeps backend implementations in the consumer project (e.g.,
    docman.backends.docling_backend.DoclingBackend) rather than in the
    loom framework itself.

    Optional backend_config in the YAML is passed as kwargs to the backend
    constructor, allowing runtime configuration without code changes.
    """
    import yaml

    from loom.worker.processor import ProcessorWorker

    with open(config) as f:
        cfg = yaml.safe_load(f)

    # The processing_backend field must be a fully qualified class path.
    backend_name = cfg.get("processing_backend")
    if not backend_name:
        raise click.ClickException("Config must specify 'processing_backend'")

    backend = _load_processing_backend(backend_name, cfg)

    actor = ProcessorWorker(
        actor_id=f"processor-{cfg['name']}-{tier}",
        config_path=config,
        backend=backend,
        nats_url=nats_url,
    )
    subject = f"loom.tasks.{cfg['name']}.{tier}"
    asyncio.run(actor.run(subject, queue_group=f"processors-{cfg['name']}"))


def _load_processing_backend(name: str, config: dict):
    """Dynamically import and instantiate a ProcessingBackend by class path.

    Backend resolution:
        1. The ``name`` must be a fully qualified Python class path containing
           at least one dot (e.g., ``mypackage.backends.DoclingBackend``).
        2. The module portion is imported via ``importlib.import_module``.
        3. The class is retrieved with ``getattr`` and instantiated.

    If the worker config contains a ``backend_config`` dict, its contents are
    passed as keyword arguments to the backend constructor.

    This design keeps the CLI generic -- backend implementations live in the
    consumer project (e.g., docman), not in the loom framework.

    Args:
        name: Fully qualified class path (e.g., ``docman.backends.DoclingBackend``).
        config: The parsed worker config dict, potentially containing
                ``backend_config`` with constructor kwargs.

    Returns:
        An instantiated backend object.

    Raises:
        click.ClickException: If the name is not a dotted path, the module
            cannot be imported, or the class is not found in the module.
    """
    if "." not in name:
        raise click.ClickException(
            f"processing_backend '{name}' must be a fully qualified class path "
            f"(e.g., 'docman.backends.DoclingBackend')"
        )

    module_path, class_name = name.rsplit(".", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as e:
        raise click.ClickException(f"Cannot import backend module '{module_path}': {e}")

    backend_class = getattr(module, class_name, None)
    if backend_class is None:
        raise click.ClickException(
            f"Backend class '{class_name}' not found in '{module_path}'"
        )

    # Pass backend_config from worker config if present (empty dict as default).
    backend_config = config.get("backend_config", {})
    return backend_class(**backend_config)


# ---------------------------------------------------------------------------
# pipeline command
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--config", required=True, help="Path to pipeline orchestrator config YAML"
)
@click.option("--nats-url", default="nats://nats:4222", help="NATS server URL")
def pipeline(config: str, nats_url: str):
    """Start a pipeline orchestrator (sequential stage execution).

    The pipeline orchestrator executes a fixed sequence of stages defined in
    the config YAML. Each stage dispatches a task to a worker and waits for
    the result before proceeding to the next stage. Stage outputs accumulate
    in a context dict and can be referenced by subsequent stages via
    dot-notation input mappings.

    Subscribes to: loom.goals.incoming
    Queue group: pipelines (allows multiple pipeline instances for HA).

    See configs/orchestrators/ for example pipeline configs.
    """
    import yaml

    from loom.orchestrator.pipeline import PipelineOrchestrator

    with open(config) as f:
        cfg = yaml.safe_load(f)

    orch = PipelineOrchestrator(
        actor_id=f"pipeline-{cfg['name']}",
        config_path=config,
        nats_url=nats_url,
    )
    asyncio.run(orch.run("loom.goals.incoming", queue_group="pipelines"))


# ---------------------------------------------------------------------------
# orchestrator command
# ---------------------------------------------------------------------------


@cli.command()
@click.option(
    "--config", required=True, help="Path to orchestrator config YAML"
)
@click.option("--nats-url", default="nats://nats:4222", help="NATS server URL")
@click.option("--redis-url", default="redis://redis:6379", help="Redis URL for checkpointing (empty to disable)")
def orchestrator(config: str, nats_url: str, redis_url: str):
    """Start the dynamic LLM-based orchestrator (OrchestratorActor).

    Unlike the pipeline orchestrator which follows a fixed stage sequence,
    the dynamic orchestrator uses an LLM to reason about which workers to
    invoke and how to combine their results. It decomposes high-level goals
    into subtasks, dispatches them, and synthesizes a final answer.

    Config fields (see configs/orchestrators/default.yaml):

    \b
        name                -- Unique orchestrator identifier
        system_prompt       -- LLM prompt governing decomposition behavior
        checkpoint          -- Context compression settings (token_threshold,
                               recent_window)
        max_concurrent_tasks -- Max subtasks dispatched at once
        timeout_seconds     -- Per-subtask timeout

    Subscribes to: loom.goals.incoming
    Queue group: orchestrators

    """
    import yaml

    from loom.orchestrator.runner import OrchestratorActor

    with open(config) as f:
        cfg = yaml.safe_load(f)

    # Build checkpoint store if redis_url is provided.
    checkpoint_store = None
    if redis_url:
        try:
            from loom.contrib.redis.store import RedisCheckpointStore
            checkpoint_store = RedisCheckpointStore(redis_url)
        except ImportError:
            logger.warning(
                "orchestrator.no_redis",
                hint="Install loom[redis] for checkpoint persistence. Continuing without checkpointing.",
            )

    actor = OrchestratorActor(
        actor_id=f"orchestrator-{cfg['name']}",
        config_path=config,
        nats_url=nats_url,
        checkpoint_store=checkpoint_store,
    )

    logger.info(
        "orchestrator.starting",
        name=cfg["name"],
        config_path=config,
        nats_url=nats_url,
        checkpointing="enabled" if checkpoint_store else "disabled",
        max_concurrent_tasks=cfg.get("max_concurrent_tasks", "not set"),
        timeout_seconds=cfg.get("timeout_seconds", "not set"),
    )

    asyncio.run(actor.run("loom.goals.incoming", queue_group="orchestrators"))


# ---------------------------------------------------------------------------
# scheduler command
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--config", required=True, help="Path to scheduler config YAML")
@click.option("--nats-url", default="nats://nats:4222", help="NATS server URL")
def scheduler(config: str, nats_url: str):
    """Start the time-driven scheduler (cron + interval dispatch).

    The scheduler reads a YAML config defining cron expressions and/or
    fixed-interval timers.  When a timer fires, it publishes an
    OrchestratorGoal or TaskMessage to the appropriate NATS subject.

    All schedules are defined at startup via config.  There are no
    runtime control messages.

    Requires the 'croniter' package for cron expression support:

    \b
        pip install loom[scheduler]

    Subscribes to: loom.scheduler.{name}  (health checks)
    Publishes to:  loom.goals.incoming / loom.tasks.incoming

    See configs/schedulers/example.yaml for a reference config.
    """
    import yaml

    from loom.scheduler.config import validate_scheduler_config
    from loom.scheduler.scheduler import SchedulerActor

    with open(config) as f:
        cfg = yaml.safe_load(f)

    errors = validate_scheduler_config(cfg, config)
    if errors:
        for err in errors:
            logger.error("scheduler.config_error", error=err)
        raise click.ClickException(
            f"Scheduler config has {len(errors)} error(s). See log above."
        )

    actor = SchedulerActor(
        actor_id=f"scheduler-{cfg['name']}",
        config_path=config,
        nats_url=nats_url,
    )

    subject = f"loom.scheduler.{cfg['name']}"
    logger.info(
        "scheduler.starting",
        name=cfg["name"],
        config_path=config,
        schedule_count=len(cfg.get("schedules", [])),
    )

    asyncio.run(actor.run(subject))


# ---------------------------------------------------------------------------
# router command
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--config", default="configs/router_rules.yaml", help="Path to router rules YAML")
@click.option("--nats-url", default="nats://nats:4222", help="NATS server URL")
def router(config: str, nats_url: str):
    """Start the deterministic task router.

    The router subscribes to loom.tasks.incoming and forwards each task
    to the appropriate worker subject (loom.tasks.{worker_type}.{tier})
    based on the rules defined in the router config YAML.

    The router does NOT use an LLM -- it is pure deterministic logic that
    routes by worker_type and model_tier, applying tier overrides and
    (eventually) rate limits from the config.

    The router runs indefinitely until the process is terminated.
    """
    from loom.bus.nats_adapter import NATSBus
    from loom.router.router import TaskRouter

    bus = NATSBus(nats_url)
    r = TaskRouter(config, bus)

    async def _run():
        """Connect, subscribe, and process messages until terminated."""
        await r.run()
        await r.process_messages()

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# submit command
# ---------------------------------------------------------------------------


@cli.command()
@click.argument("goal")
@click.option("--nats-url", default="nats://nats:4222", help="NATS server URL")
@click.option(
    "--context",
    multiple=True,
    help="Key=value pairs for goal context (repeatable)",
)
def submit(goal: str, nats_url: str, context: tuple[str, ...]):
    """Submit a goal to the pipeline orchestrator.

    Publishes an OrchestratorGoal message to loom.goals.incoming. A running
    pipeline or dynamic orchestrator (loom pipeline / loom orchestrator)
    must be listening on that subject to process the goal.

    Context is passed as repeatable key=value pairs, e.g.:

    \b
        loom submit "Process document" \\
            --context file_ref=test.pdf \\
            --context lang=en
    """
    import nats as nats_lib

    from loom.core.messages import OrchestratorGoal

    # Parse context key=value pairs into a dict.
    ctx = {}
    for item in context:
        if "=" not in item:
            raise click.ClickException(f"Context must be key=value, got: {item}")
        k, v = item.split("=", 1)
        ctx[k] = v

    async def _submit():
        """Connect to NATS, publish the goal, and drain the connection."""
        nc = await nats_lib.connect(nats_url)
        g = OrchestratorGoal(instruction=goal, context=ctx)
        await nc.publish("loom.goals.incoming", g.model_dump_json().encode())
        await nc.drain()
        click.echo(f"Submitted goal: {g.goal_id}")

    asyncio.run(_submit())


# ---------------------------------------------------------------------------
# mcp command
# ---------------------------------------------------------------------------


@cli.command()
@click.option("--config", required=True, help="Path to MCP gateway config YAML")
@click.option(
    "--transport",
    default="stdio",
    type=click.Choice(["stdio", "streamable-http"]),
    help="MCP transport (default: stdio)",
)
@click.option("--host", default="127.0.0.1", help="HTTP host (streamable-http only)")
@click.option("--port", default=8000, type=int, help="HTTP port (streamable-http only)")
def mcp(config: str, transport: str, host: str, port: int):
    """Start an MCP server exposing LOOM tools and resources.

    Reads an MCP gateway config YAML and starts an MCP server that exposes
    LOOM workers, pipelines, and query backends as MCP tools. Workspace
    files can optionally be exposed as MCP resources.

    \b
    Transports:
        stdio            -- Standard I/O (default, used by most MCP clients)
        streamable-http  -- HTTP server (requires uvicorn)

    Requires the 'mcp' package:

    \b
        pip install loom[mcp]

    See docs/mcp.md for config format and examples.
    """
    from loom.mcp import create_server, run_stdio, run_streamable_http

    server, gateway = create_server(config)

    tool_count = len(gateway.tool_registry)
    has_resources = gateway.resources is not None
    logger.info(
        "mcp.starting",
        config_path=config,
        transport=transport,
        tools=tool_count,
        resources="enabled" if has_resources else "disabled",
    )

    if transport == "stdio":
        run_stdio(server, gateway)
    else:
        run_streamable_http(server, gateway, host=host, port=port)


if __name__ == "__main__":
    cli()
