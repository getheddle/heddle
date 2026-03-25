"""
Config validation CLI.

Validates worker, pipeline, and orchestrator YAML configs without
starting any infrastructure. Auto-detects config type from content.

Usage::

    loom validate configs/workers/my_worker.yaml
    loom validate configs/workers/*.yaml configs/orchestrators/*.yaml
    loom validate --all
"""

from __future__ import annotations

from pathlib import Path

import click


def _detect_config_type(config: dict) -> str | None:
    """Auto-detect config type from content.

    Returns:
        ``"worker"``, ``"pipeline"``, ``"orchestrator"``, or ``None``.
    """
    if "pipeline_stages" in config:
        return "pipeline"
    if "system_prompt" in config or "processing_backend" in config or "worker_kind" in config:
        return "worker"
    if "available_workers" in config:
        return "orchestrator"
    # Fallback: check for worker-like fields
    if "input_schema" in config and "output_schema" in config:
        return "worker"
    return None


def _validate_file(path: Path) -> tuple[bool, str, list[str]]:
    """Validate a single config file.

    Returns:
        (valid, config_type, errors)
    """
    import yaml

    from loom.core.config import (
        validate_orchestrator_config,
        validate_pipeline_config,
        validate_worker_config,
    )

    if not path.exists():
        return False, "unknown", [f"File not found: {path}"]

    try:
        with path.open() as f:
            config = yaml.safe_load(f)
    except yaml.YAMLError as exc:
        return False, "unknown", [f"Invalid YAML: {exc}"]

    if not config or not isinstance(config, dict):
        return False, "unknown", ["File is empty or not a YAML mapping"]

    config_type = _detect_config_type(config)
    if config_type is None:
        return (
            False,
            "unknown",
            ["Cannot detect config type (not a worker, pipeline, or orchestrator)"],
        )

    if config_type == "worker":
        errors = validate_worker_config(config, path=str(path))
    elif config_type == "pipeline":
        errors = validate_pipeline_config(config, path=str(path))
    else:
        errors = validate_orchestrator_config(config, path=str(path))

    return len(errors) == 0, config_type, errors


@click.command("validate")
@click.argument("paths", nargs=-1, type=click.Path())
@click.option("--all", "validate_all", is_flag=True, default=False, help="Validate all configs.")
@click.option("--configs-dir", default="configs/", help="Root config directory.", show_default=True)
def validate(paths: tuple[str, ...], validate_all: bool, configs_dir: str) -> None:
    """Validate worker, pipeline, and orchestrator configs.

    Auto-detects config type from file content.
    Exit code 0 if all valid, 1 if any errors.
    """
    files: list[Path] = []

    if validate_all:
        root = Path(configs_dir)
        if not root.is_dir():
            raise click.ClickException(f"Config directory not found: {configs_dir}")
        files = sorted(
            p
            for p in root.rglob("*.yaml")
            if p.name != "_template.yaml" and not p.name.startswith(".")
        )
        if not files:
            raise click.ClickException(f"No YAML files found in {configs_dir}")
    elif paths:
        files = [Path(p) for p in paths]
    else:
        raise click.ClickException("Provide config file paths or use --all.")

    click.echo()
    has_errors = False
    valid_count = 0
    error_count = 0

    for path in files:
        ok, config_type, errors = _validate_file(path)
        if ok:
            valid_count += 1
            click.echo(
                click.style("  ✓ ", fg="green")
                + click.style(f"[{config_type}]", fg="cyan")
                + f" {path}"
            )
        else:
            error_count += 1
            has_errors = True
            click.echo(
                click.style("  ✗ ", fg="red")
                + click.style(f"[{config_type}]", fg="cyan")
                + f" {path}"
            )
            for err in errors:
                click.echo(click.style(f"    → {err}", fg="red"))

    click.echo()
    if has_errors:
        click.echo(click.style(f"  {error_count} invalid, {valid_count} valid", fg="red"))
    else:
        click.echo(click.style(f"  {valid_count} config(s) valid", fg="green"))
    click.echo()

    if has_errors:
        raise SystemExit(1)
