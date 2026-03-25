"""
Interactive setup wizard for Loom.

Detects existing configuration, probes for Ollama, prompts for API keys,
and writes ~/.loom/config.yaml. Re-runnable: detects existing config and
offers to update.
"""

from __future__ import annotations

from pathlib import Path

import click

from loom.cli.config import DEFAULT_CONFIG_PATH, load_config, save_config

# ---------------------------------------------------------------------------
# Detection helpers
# ---------------------------------------------------------------------------


def _detect_ollama(url: str = "http://localhost:11434") -> tuple[bool, list[str]]:
    """Probe Ollama /api/tags endpoint.

    Returns:
        (reachable, model_name_list)
    """
    import httpx

    try:
        resp = httpx.get(f"{url}/api/tags", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            return True, models
    except (httpx.ConnectError, httpx.TimeoutException, Exception):
        pass
    return False, []


def _test_anthropic_key(api_key: str) -> bool:
    """Quick validation of Anthropic API key via models endpoint."""
    import httpx

    try:
        resp = httpx.get(
            "https://api.anthropic.com/v1/models",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2024-10-22",
            },
            timeout=5.0,
        )
        return resp.status_code == 200
    except (httpx.ConnectError, httpx.TimeoutException, Exception):
        return False


def _find_telegram_exports(directory: str) -> list[str]:
    """Scan directory for result*.json Telegram exports."""
    path = Path(directory).expanduser()
    if not path.is_dir():
        return []
    return sorted(str(f) for f in path.glob("result*.json"))


# ---------------------------------------------------------------------------
# Setup command
# ---------------------------------------------------------------------------


@click.command()
@click.option(
    "--config-path",
    default=DEFAULT_CONFIG_PATH,
    help="Config file path.",
    show_default=True,
)
@click.option(
    "--non-interactive",
    is_flag=True,
    default=False,
    help="Use defaults without prompting.",
)
def setup(config_path: str, non_interactive: bool) -> None:  # noqa: PLR0912, PLR0915
    """Interactive setup wizard for Loom.

    Detects Ollama, prompts for API keys, configures RAG data sources,
    and writes ~/.loom/config.yaml.
    """
    expanded_path = str(Path(config_path).expanduser())

    click.echo()
    click.echo(click.style("  Loom Setup Wizard", fg="cyan", bold=True))
    click.echo(click.style("  ─────────────────", fg="cyan"))
    click.echo()

    # Load existing config
    config = load_config(config_path)
    if Path(expanded_path).exists():
        click.echo(click.style("  ✓ Existing config found", fg="green"))
        click.echo(f"    {expanded_path}")
        click.echo()

    # ── Section 1: LLM Backend ──────────────────────────────────────────
    click.echo(click.style("  [1/4] LLM Backend", fg="yellow", bold=True))
    click.echo()

    # Detect Ollama
    probe_url = config.ollama_url or "http://localhost:11434"
    ollama_found, models = _detect_ollama(probe_url)
    if ollama_found:
        click.echo(click.style(f"  ✓ Ollama detected at {probe_url}", fg="green"))
        if models:
            click.echo(f"    Models: {', '.join(models[:8])}")
            if len(models) > 8:
                click.echo(f"    ... and {len(models) - 8} more")
        config.ollama_url = probe_url
    else:
        click.echo(click.style("  ✗ Ollama not detected", fg="red"))
        if not non_interactive:
            custom_url = click.prompt(
                "    Ollama URL (or press Enter to skip)",
                default="",
                show_default=False,
            )
            if custom_url:
                found, models = _detect_ollama(custom_url)
                if found:
                    config.ollama_url = custom_url
                    click.echo(click.style(f"  ✓ Ollama found at {custom_url}", fg="green"))
                else:
                    click.echo(click.style(f"  ✗ Cannot reach {custom_url}", fg="red"))
    click.echo()

    # Anthropic API key
    if config.anthropic_api_key:
        masked = config.anthropic_api_key[:7] + "..." + config.anthropic_api_key[-4:]
        click.echo(f"  Anthropic API key: {masked}")
        if not non_interactive and click.confirm("    Update key?", default=False):
            new_key = click.prompt("    New API key", hide_input=True)
            if _test_anthropic_key(new_key):
                config.anthropic_api_key = new_key
                click.echo(click.style("  ✓ Key validated", fg="green"))
            else:
                click.echo(click.style("  ✗ Key validation failed (saved anyway)", fg="yellow"))
                config.anthropic_api_key = new_key
    elif not non_interactive:
        key = click.prompt(
            "    Anthropic API key (or press Enter to skip)",
            default="",
            hide_input=True,
            show_default=False,
        )
        if key:
            if _test_anthropic_key(key):
                config.anthropic_api_key = key
                click.echo(click.style("  ✓ Key validated", fg="green"))
            else:
                click.echo(click.style("  ✗ Validation failed (saved anyway)", fg="yellow"))
                config.anthropic_api_key = key

    if not config.ollama_url and not config.anthropic_api_key:
        click.echo()
        click.echo(click.style("  ⚠ No LLM backend configured.", fg="yellow"))
        click.echo("    Set OLLAMA_URL or ANTHROPIC_API_KEY to use LLM features.")

    click.echo()

    # ── Section 2: Embedding Model ──────────────────────────────────────
    click.echo(click.style("  [2/4] Embedding Model", fg="yellow", bold=True))
    click.echo()

    if ollama_found:
        has_embed = any(config.embedding_model in m for m in models)
        if has_embed:
            click.echo(click.style(f"  ✓ {config.embedding_model} available", fg="green"))
        else:
            click.echo(click.style(f"  ✗ {config.embedding_model} not found", fg="red"))
            if not non_interactive and click.confirm(
                f"    Pull {config.embedding_model}?", default=True
            ):
                click.echo(f"    Pulling {config.embedding_model}... (this may take a few minutes)")
                _pull_embedding_model(probe_url, config.embedding_model)

        if not non_interactive:
            custom_model = click.prompt(
                "    Embedding model",
                default=config.embedding_model,
            )
            config.embedding_model = custom_model
    else:
        click.echo("  Skipped (no Ollama detected)")

    click.echo()

    # ── Section 3: Data Sources ─────────────────────────────────────────
    click.echo(click.style("  [3/4] Data Sources", fg="yellow", bold=True))
    click.echo()

    if not non_interactive:
        data_dir = click.prompt(
            "    Telegram export directory (or press Enter to skip)",
            default=config.rag_data_dir or "",
            show_default=bool(config.rag_data_dir),
        )
        if data_dir:
            exports = _find_telegram_exports(data_dir)
            if exports:
                click.echo(click.style(f"  ✓ Found {len(exports)} export file(s)", fg="green"))
                for e in exports[:5]:
                    click.echo(f"    {Path(e).name}")
                if len(exports) > 5:
                    click.echo(f"    ... and {len(exports) - 5} more")
            else:
                click.echo(click.style("  ✗ No result*.json files found", fg="red"))
            config.rag_data_dir = data_dir
    elif config.rag_data_dir:
        click.echo(f"  Data dir: {config.rag_data_dir}")
    else:
        click.echo("  No data directory configured.")

    click.echo()

    # ── Section 4: Summary ──────────────────────────────────────────────
    click.echo(click.style("  [4/4] Summary", fg="yellow", bold=True))
    click.echo()

    click.echo(f"    Ollama:      {config.ollama_url or 'not configured'}")
    if config.anthropic_api_key:
        masked = config.anthropic_api_key[:7] + "..." + config.anthropic_api_key[-4:]
        click.echo(f"    Anthropic:   {masked}")
    else:
        click.echo("    Anthropic:   not configured")
    click.echo(f"    Embeddings:  {config.embedding_model}")
    click.echo(f"    Data dir:    {config.rag_data_dir or 'not set'}")
    click.echo(f"    Vector store: {config.rag_vector_store}")
    click.echo()

    save_config(config, config_path)
    click.echo(click.style(f"  ✓ Config saved to {expanded_path}", fg="green"))
    click.echo()

    # Next steps
    click.echo(click.style("  Next steps:", fg="cyan", bold=True))
    if config.rag_data_dir:
        click.echo(f"    loom rag ingest {config.rag_data_dir}/result*.json")
    else:
        click.echo("    loom rag ingest /path/to/telegram/exports/*.json")
    click.echo('    loom rag search "your query here"')
    click.echo("    loom rag serve")
    click.echo()


def _pull_embedding_model(url: str, model: str) -> bool:  # pragma: no cover
    """Pull an embedding model via Ollama /api/pull."""
    import httpx

    try:
        resp = httpx.post(
            f"{url}/api/pull",
            json={"name": model},
            timeout=600.0,
        )
        return resp.status_code == 200
    except Exception:
        click.echo(click.style("    Pull failed. Run manually: ollama pull " + model, fg="red"))
        return False
