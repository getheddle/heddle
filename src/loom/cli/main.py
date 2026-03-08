"""
Loom CLI. Entry point for running components.
"""
import asyncio

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
    """Start a worker actor."""
    import os

    import yaml

    from loom.worker.backends import AnthropicBackend, OllamaBackend
    from loom.worker.runner import WorkerActor

    with open(config) as f:
        cfg = yaml.safe_load(f)

    # Build backends from environment
    backends = {}
    if os.getenv("OLLAMA_URL"):
        backends["local"] = OllamaBackend(base_url=os.getenv("OLLAMA_URL"))
    if os.getenv("ANTHROPIC_API_KEY"):
        backends["standard"] = AnthropicBackend(api_key=os.getenv("ANTHROPIC_API_KEY"))
        backends["frontier"] = AnthropicBackend(
            api_key=os.getenv("ANTHROPIC_API_KEY"),
            model=os.getenv("FRONTIER_MODEL", "claude-opus-4-20250514"),
        )

    actor = WorkerActor(
        actor_id=f"worker-{cfg['name']}-{tier}",
        config_path=config,
        backends=backends,
        nats_url=nats_url,
    )
    subject = f"loom.tasks.{cfg['name']}.{tier}"
    asyncio.run(actor.run(subject, queue_group=f"workers-{cfg['name']}"))


@cli.command()
@click.option("--config", default="configs/router_rules.yaml")
@click.option("--nats-url", default="nats://nats:4222")
def router(config: str, nats_url: str):
    """Start the task router."""
    from loom.bus.nats_adapter import NATSBus
    from loom.router.router import TaskRouter

    bus = NATSBus(nats_url)
    r = TaskRouter(config, bus)
    asyncio.run(r.run())
    # Keep alive
    asyncio.get_event_loop().run_forever()


@cli.command()
@click.argument("goal")
@click.option("--nats-url", default="nats://nats:4222")
def submit(goal: str, nats_url: str):
    """Submit a goal to the orchestrator (for testing)."""
    import nats as nats_lib

    from loom.core.messages import OrchestratorGoal

    async def _submit():
        nc = await nats_lib.connect(nats_url)
        g = OrchestratorGoal(instruction=goal)
        await nc.publish("loom.goals.incoming", g.model_dump_json().encode())
        await nc.drain()
        click.echo(f"Submitted goal: {g.goal_id}")

    asyncio.run(_submit())


if __name__ == "__main__":
    cli()
