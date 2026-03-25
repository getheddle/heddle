"""
Interactive scaffolding for worker and pipeline configs.

Generates YAML configs from interactive prompts, making YAML a generated
artifact rather than a hand-written primary interface.

Commands::

    loom new worker     # scaffold a worker config
    loom new pipeline   # scaffold a pipeline config
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import click


def _validate_name(name: str) -> str | None:
    """Validate a config name. Returns error message or None."""
    if not name:
        return "Name is required."
    if not re.match(r"^[a-z][a-z0-9_]*$", name):
        return "Name must be lowercase letters, digits, and underscores (start with a letter)."
    return None


def _build_schema(field_names: str) -> dict[str, Any]:
    """Build a JSON Schema object from comma-separated field names.

    All fields default to ``type: string``.
    """
    names = [n.strip() for n in field_names.split(",") if n.strip()]
    if not names:
        return {"type": "object", "required": [], "properties": {}}
    return {
        "type": "object",
        "required": names,
        "properties": {n: {"type": "string"} for n in names},
    }


def _list_workers(configs_dir: Path) -> list[str]:
    """List available worker names from configs/workers/."""
    workers_dir = configs_dir / "workers"
    if not workers_dir.is_dir():
        return []
    return sorted(
        p.stem
        for p in workers_dir.glob("*.yaml")
        if p.name != "_template.yaml" and not p.name.startswith(".")
    )


# ---------------------------------------------------------------------------
# Group
# ---------------------------------------------------------------------------


@click.group()
def new() -> None:
    """Scaffold new worker and pipeline configs."""


# ---------------------------------------------------------------------------
# loom new worker
# ---------------------------------------------------------------------------


@new.command()
@click.option("--name", default=None, help="Worker name (lowercase, underscores).")
@click.option(
    "--kind",
    default=None,
    type=click.Choice(["llm", "processor"]),
    help="Worker kind.",
)
@click.option(
    "--tier",
    default=None,
    type=click.Choice(["local", "standard", "frontier"]),
    help="Default model tier.",
)
@click.option("--configs-dir", default="configs/", help="Config directory.", show_default=True)
@click.option("--non-interactive", is_flag=True, default=False, help="Use defaults, no prompts.")
def worker(  # noqa: PLR0912, PLR0915
    name: str | None,
    kind: str | None,
    tier: str | None,
    configs_dir: str,
    non_interactive: bool,
) -> None:
    """Scaffold a new worker config interactively."""
    import yaml

    from loom.core.config import validate_worker_config

    configs = Path(configs_dir)

    click.echo()
    click.echo(click.style("  New Worker", fg="cyan", bold=True))
    click.echo()

    # 1. Name
    if not name and not non_interactive:
        name = click.prompt("  Name (lowercase, underscores)")
    if not name:
        name = "my_worker"
    err = _validate_name(name)
    if err:
        raise click.ClickException(err)

    dest = configs / "workers" / f"{name}.yaml"
    if dest.exists():
        raise click.ClickException(f"Config already exists: {dest}")

    # 2. Kind
    if not kind and not non_interactive:
        kind = click.prompt("  Kind", type=click.Choice(["llm", "processor"]), default="llm")
    if not kind:
        kind = "llm"

    config: dict[str, Any] = {
        "name": name,
        "reset_after_task": True,
    }

    # 3. Kind-specific fields
    if kind == "llm":
        if not tier and not non_interactive:
            tier = click.prompt(
                "  Model tier",
                type=click.Choice(["local", "standard", "frontier"]),
                default="local",
            )
        config["default_model_tier"] = tier or "local"

        if not non_interactive:
            click.echo("  System prompt (one line, or leave empty to open editor):")
            prompt_text = click.prompt("  ", default="", show_default=False)
            if not prompt_text:
                prompt_text = click.edit("# Write the system prompt for this worker.\n")
            if prompt_text:
                config["system_prompt"] = prompt_text.strip()
            else:
                config["system_prompt"] = (
                    f"You are a {name} worker. Process the input and return structured JSON output."
                )
        else:
            config["system_prompt"] = (
                f"You are a {name} worker. Process the input and return structured JSON output."
            )

        config["max_input_tokens"] = 8000
        config["max_output_tokens"] = 1000
        timeout = 30
    else:
        if not non_interactive:
            backend = click.prompt("  Processing backend (dotted class path)")
        else:
            backend = "mypackage.backend.MyBackend"
        config["worker_kind"] = "processor"
        config["processing_backend"] = backend
        timeout = 60

    # 4. Input schema
    if not non_interactive:
        click.echo("  Input fields (comma-separated, e.g. text,language):")
        input_fields = click.prompt("  ", default="text")
    else:
        input_fields = "text"
    config["input_schema"] = _build_schema(input_fields)

    # 5. Output schema
    if not non_interactive:
        click.echo("  Output fields (comma-separated, e.g. result,confidence):")
        output_fields = click.prompt("  ", default="result")
    else:
        output_fields = "result"
    config["output_schema"] = _build_schema(output_fields)

    # 6. Timeout
    if not non_interactive:
        timeout = click.prompt("  Timeout (seconds)", default=timeout, type=int)
    config["timeout_seconds"] = timeout

    # 7. Validate
    errors = validate_worker_config(config)
    if errors:
        click.echo()
        click.echo(click.style("  Validation errors:", fg="red"))
        for err in errors:
            click.echo(click.style(f"    → {err}", fg="red"))
        click.echo()
        raise click.ClickException("Fix the errors above and try again.")

    # 8. Write
    dest.parent.mkdir(parents=True, exist_ok=True)
    config_yaml = yaml.dump(config, default_flow_style=False, sort_keys=False)
    dest.write_text(config_yaml)

    click.echo()
    click.echo(click.style(f"  ✓ Created {dest}", fg="green"))
    click.echo()
    click.echo(click.style("  Next steps:", fg="cyan"))
    click.echo(f"    loom validate {dest}")
    click.echo("    loom workshop  # test it in the web UI")
    click.echo()


# ---------------------------------------------------------------------------
# loom new pipeline
# ---------------------------------------------------------------------------


@new.command()
@click.option("--name", default=None, help="Pipeline name.")
@click.option("--configs-dir", default="configs/", help="Config directory.", show_default=True)
@click.option("--non-interactive", is_flag=True, default=False, help="Use defaults, no prompts.")
def pipeline(  # noqa: PLR0912, PLR0915
    name: str | None,
    configs_dir: str,
    non_interactive: bool,
) -> None:
    """Scaffold a new pipeline config interactively."""
    import yaml

    from loom.core.config import validate_pipeline_config

    configs = Path(configs_dir)

    click.echo()
    click.echo(click.style("  New Pipeline", fg="cyan", bold=True))
    click.echo()

    # 1. Name
    if not name and not non_interactive:
        name = click.prompt("  Pipeline name")
    if not name:
        name = "my_pipeline"
    err = _validate_name(name)
    if err:
        raise click.ClickException(err)

    dest = configs / "orchestrators" / f"{name}.yaml"
    if dest.exists():
        raise click.ClickException(f"Config already exists: {dest}")

    # 2. Show available workers
    available = _list_workers(configs)
    if available and not non_interactive:
        click.echo(f"  Available workers: {', '.join(available)}")
        click.echo()

    # 3. Build stages
    stages: list[dict[str, Any]] = []
    prior_stage_names: list[str] = []

    if non_interactive:
        # Non-interactive: create a one-stage pipeline
        stages.append(
            {
                "name": "step1",
                "worker_type": available[0] if available else "summarizer",
                "input_mapping": {"text": "goal.context.text"},
            }
        )
    else:
        while True:
            stage_num = len(stages) + 1
            click.echo(click.style(f"  Stage {stage_num}:", fg="yellow"))

            # Worker type
            worker_type = click.prompt("    Worker type")

            # Stage name
            stage_name = click.prompt("    Stage name", default=worker_type)
            err = _validate_name(stage_name)
            if err:
                click.echo(click.style(f"    {err}", fg="red"))
                continue

            # Input mapping
            mapping: dict[str, str] = {}
            click.echo("    Input mapping (enter field=path pairs, empty line to finish):")
            if not prior_stage_names:
                click.echo("      Paths: goal.context.{field} for goal context fields")
            else:
                click.echo(
                    f"      Paths: goal.context.{{field}} or "
                    f"{'/'.join(prior_stage_names)}.output.{{field}}"
                )

            while True:
                pair = click.prompt("      ", default="", show_default=False)
                if not pair:
                    break
                if "=" not in pair:
                    click.echo(
                        click.style(
                            "      Must be field=path (e.g. text=goal.context.text)",
                            fg="red",
                        )
                    )
                    continue
                k, v = pair.split("=", 1)
                mapping[k.strip()] = v.strip()

            # If no mapping entered, provide a default
            if not mapping and not prior_stage_names:
                mapping = {"text": "goal.context.text"}
                click.echo("      (default: text=goal.context.text)")

            stage: dict[str, Any] = {
                "name": stage_name,
                "worker_type": worker_type,
            }
            if mapping:
                stage["input_mapping"] = mapping

            stages.append(stage)
            prior_stage_names.append(stage_name)
            click.echo()

            if not click.confirm("  Add another stage?", default=False):
                break

    if not stages:
        raise click.ClickException("Pipeline must have at least one stage.")

    # 4. Timeout
    if not non_interactive:
        timeout = click.prompt("  Pipeline timeout (seconds)", default=300, type=int)
    else:
        timeout = 300

    # 5. Build config
    config: dict[str, Any] = {
        "name": name,
        "timeout_seconds": timeout,
        "pipeline_stages": stages,
    }

    # 6. Validate
    errors = validate_pipeline_config(config)
    if errors:
        click.echo()
        click.echo(click.style("  Validation errors:", fg="red"))
        for err in errors:
            click.echo(click.style(f"    → {err}", fg="red"))
        click.echo()
        raise click.ClickException("Fix the errors above and try again.")

    # 7. Write
    dest.parent.mkdir(parents=True, exist_ok=True)
    config_yaml = yaml.dump(config, default_flow_style=False, sort_keys=False)
    dest.write_text(config_yaml)

    click.echo()
    click.echo(click.style(f"  ✓ Created {dest}", fg="green"))
    click.echo(f"    {len(stages)} stage(s): {' → '.join(s['name'] for s in stages)}")
    click.echo()
    click.echo(click.style("  Next steps:", fg="cyan"))
    click.echo(f"    loom validate {dest}")
    click.echo("    loom workshop  # visualize the pipeline")
    click.echo()
