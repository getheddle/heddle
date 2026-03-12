"""
Loom CLI — entry point for running all Loom components.

Commands:
    loom worker     — Start an LLM worker (requires OLLAMA_URL or ANTHROPIC_API_KEY)
    loom processor  — Start a non-LLM processor worker (e.g., DoclingBackend)
    loom pipeline   — Start a pipeline orchestrator (sequential stage execution)
    loom router     — Start the deterministic task router
    loom submit     — Submit a goal to the orchestrator

Typical local dev startup (5 terminals):
    1. docker run -p 4222:4222 nats:latest
    2. loom router --config configs/router_rules.yaml --nats-url nats://localhost:4222
    3. loom processor --config configs/workers/doc_extractor.yaml --nats-url nats://localhost:4222
    4. loom worker --config configs/workers/doc_classifier.yaml --tier local --nats-url nats://localhost:4222
    5. loom submit "Process document" --context file_ref=test.pdf --nats-url nats://localhost:4222

NOTE: There is no 'orchestrator' CLI command yet (OrchestratorActor is a stub).
      The Dockerfile.orchestrator references a nonexistent 'loom orchestrator'
      command — see FIXME in that file.
"""
import asyncio
import importlib

import click
import structlog

structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)


@click.group()
def cli():
    """Loom -- Lightweight Orchestrated Operational Mesh"""
    pass


@cli.command()
@click.option("--config", required=True, help="Path to worker config YAML")
@click.option("--nats-url", default="nats://nats:4222")
@click.option("--tier", default="standard", help="Model tier this worker serves")
def worker(config: str, nats_url: str, tier: str):
    """Start an LLM worker actor.

    Backends are resolved from environment variables:
        OLLAMA_URL       → OllamaBackend (serves "local" tier)
        ANTHROPIC_API_KEY → AnthropicBackend (serves "standard" and "frontier" tiers)
        FRONTIER_MODEL    → Override frontier model (default: claude-opus-4-20250514)

    The worker subscribes to: loom.tasks.{worker_name}.{tier}
    with queue group: workers-{worker_name} (enables horizontal scaling).
    """
    import os

    import yaml

    from loom.worker.backends import AnthropicBackend, OllamaBackend
    from loom.worker.runner import LLMWorker

    with open(config) as f:
        cfg = yaml.safe_load(f)

    # Build backends from environment.
    # Only tiers with configured backends can be served.
    # TODO: Warn if --tier is specified but no matching backend is configured.
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

    actor = LLMWorker(
        actor_id=f"worker-{cfg['name']}-{tier}",
        config_path=config,
        backends=backends,
        nats_url=nats_url,
    )
    subject = f"loom.tasks.{cfg['name']}.{tier}"
    asyncio.run(actor.run(subject, queue_group=f"workers-{cfg['name']}"))


@cli.command()
@click.option("--config", required=True, help="Path to processor worker config YAML")
@click.option("--nats-url", default="nats://nats:4222")
@click.option("--tier", default="local", help="Tier this processor serves")
def processor(config: str, nats_url: str, tier: str):
    """Start a processor (non-LLM) worker actor.

    The processing_backend is loaded by fully qualified class path from the
    worker config YAML. This keeps backend implementations in the consumer
    project (e.g., docman.backends.docling_backend.DoclingBackend).

    Optional backend_config in YAML is passed as kwargs to the backend constructor.
    """
    import yaml

    from loom.worker.processor import ProcessorWorker

    with open(config) as f:
        cfg = yaml.safe_load(f)

    # Resolve backend from config
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
    """
    Load a ProcessingBackend by name.

    Backend resolution:
    1. If name contains a dot, treat as a fully qualified class path
       (e.g., "mypackage.backends.DoclingBackend")
    2. Otherwise, raise an error with guidance

    This keeps the CLI generic — backend implementations live in the
    consumer project (e.g., docman), not in the loom framework.
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
        raise click.ClickException(f"Backend class '{class_name}' not found in '{module_path}'")

    # Pass backend_config from worker config if present
    backend_config = config.get("backend_config", {})
    return backend_class(**backend_config)


@cli.command()
@click.option("--config", required=True, help="Path to pipeline orchestrator config YAML")
@click.option("--nats-url", default="nats://nats:4222")
def pipeline(config: str, nats_url: str):
    """Start a pipeline orchestrator."""
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


@cli.command()
@click.option("--config", default="configs/router_rules.yaml")
@click.option("--nats-url", default="nats://nats:4222")
def router(config: str, nats_url: str):
    """Start the task router."""
    from loom.bus.nats_adapter import NATSBus
    from loom.router.router import TaskRouter

    bus = NATSBus(nats_url)
    r = TaskRouter(config, bus)

    async def _run():
        await r.run()
        await asyncio.Event().wait()  # Block forever after subscribing

    asyncio.run(_run())


@cli.command()
@click.argument("goal")
@click.option("--nats-url", default="nats://nats:4222")
@click.option("--context", multiple=True, help="Key=value pairs for goal context (repeatable)")
def submit(goal: str, nats_url: str, context: tuple[str, ...]):
    """Submit a goal to the pipeline orchestrator.

    Publishes an OrchestratorGoal to loom.goals.incoming. A running
    pipeline orchestrator (loom pipeline) must be listening.

    Context is passed as key=value pairs, e.g.:
        loom submit "Process document" --context file_ref=test.pdf --context lang=en
    """
    import nats as nats_lib

    from loom.core.messages import OrchestratorGoal

    # Parse context key=value pairs
    ctx = {}
    for item in context:
        if "=" not in item:
            raise click.ClickException(f"Context must be key=value, got: {item}")
        k, v = item.split("=", 1)
        ctx[k] = v

    async def _submit():
        nc = await nats_lib.connect(nats_url)
        g = OrchestratorGoal(instruction=goal, context=ctx)
        await nc.publish("loom.goals.incoming", g.model_dump_json().encode())
        await nc.drain()
        click.echo(f"Submitted goal: {g.goal_id}")

    asyncio.run(_submit())


if __name__ == "__main__":
    cli()
