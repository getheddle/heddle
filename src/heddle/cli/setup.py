"""
Interactive setup wizard for Heddle.

Detects existing configuration, probes for Ollama and LM Studio, prompts for
API keys, and writes ~/.heddle/config.yaml. Re-runnable: detects existing
config and offers to update.
"""

from __future__ import annotations

from pathlib import Path

import click

from heddle.cli.config import DEFAULT_CONFIG_PATH, load_config, save_config

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


def _detect_lm_studio(url: str = "http://localhost:1234/v1") -> tuple[bool, list[str]]:
    """Probe LM Studio /v1/models endpoint.

    Accepts ``http://host:port`` or ``http://host:port/v1``.

    Returns:
        (reachable, model_id_list)
    """
    import httpx

    base = url.rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    try:
        resp = httpx.get(f"{base}/models", timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            models = [m.get("id", "") for m in data.get("data", [])]
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


def _looks_like_embedding_model(name: str) -> bool:
    """Heuristic for picking embedding models out of an LM Studio model list."""
    n = name.lower()
    return "embed" in n or "e5" in n or "bge" in n or "nomic" in n


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
    """Interactive setup wizard for Heddle.

    Detects local LLM runtimes (LM Studio + Ollama), prompts for API
    keys, configures RAG data sources, and writes ~/.heddle/config.yaml.
    """
    expanded_path = str(Path(config_path).expanduser())

    click.echo()
    click.echo(click.style("  Heddle Setup Wizard", fg="cyan", bold=True))
    click.echo(click.style("  ─────────────────", fg="cyan"))
    click.echo()

    # Load existing config
    config = load_config(config_path)
    if Path(expanded_path).exists():
        click.echo(click.style("  ✓ Existing config found", fg="green"))
        click.echo(f"    {expanded_path}")
        click.echo()

    # ── Section 1: LLM Backend ──────────────────────────────────────────
    click.echo(click.style("  [1/4] LLM Backend (local)", fg="yellow", bold=True))
    click.echo()

    # Detect LM Studio
    lms_probe_url = config.lm_studio_url or "http://localhost:1234/v1"
    lm_studio_found, lm_studio_models = _detect_lm_studio(lms_probe_url)
    if lm_studio_found:
        click.echo(click.style(f"  ✓ LM Studio detected at {lms_probe_url}", fg="green"))
        if lm_studio_models:
            click.echo(f"    Models: {', '.join(lm_studio_models[:8])}")
            if len(lm_studio_models) > 8:
                click.echo(f"    ... and {len(lm_studio_models) - 8} more")
        config.lm_studio_url = lms_probe_url
    else:
        click.echo(click.style("  ✗ LM Studio not detected", fg="red"))
        if not non_interactive:
            custom_url = click.prompt(
                "    LM Studio URL (or press Enter to skip)",
                default="",
                show_default=False,
            )
            if custom_url:
                found, lm_studio_models = _detect_lm_studio(custom_url)
                lm_studio_found = found
                if found:
                    config.lm_studio_url = custom_url
                    click.echo(click.style(f"  ✓ LM Studio found at {custom_url}", fg="green"))
                else:
                    click.echo(click.style(f"  ✗ Cannot reach {custom_url}", fg="red"))
    click.echo()

    # Detect Ollama
    probe_url = config.ollama_url or "http://localhost:11434"
    ollama_found, ollama_models = _detect_ollama(probe_url)
    if ollama_found:
        click.echo(click.style(f"  ✓ Ollama detected at {probe_url}", fg="green"))
        if ollama_models:
            click.echo(f"    Models: {', '.join(ollama_models[:8])}")
            if len(ollama_models) > 8:
                click.echo(f"    ... and {len(ollama_models) - 8} more")
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
                found, ollama_models = _detect_ollama(custom_url)
                ollama_found = found
                if found:
                    config.ollama_url = custom_url
                    click.echo(click.style(f"  ✓ Ollama found at {custom_url}", fg="green"))
                else:
                    click.echo(click.style(f"  ✗ Cannot reach {custom_url}", fg="red"))
    click.echo()

    # If both are configured, ask which one wins the local tier.
    if config.lm_studio_url and config.ollama_url and not non_interactive:
        choice = click.prompt(
            "    Both LM Studio and Ollama are configured. "
            "Which should serve the local tier by default?",
            type=click.Choice(["lmstudio", "ollama"]),
            default=config.local_backend or "lmstudio",
        )
        config.local_backend = choice
    elif config.lm_studio_url and not config.ollama_url:
        config.local_backend = "lmstudio"
    elif config.ollama_url and not config.lm_studio_url:
        config.local_backend = "ollama"

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

    if not config.lm_studio_url and not config.ollama_url and not config.anthropic_api_key:
        click.echo()
        click.echo(click.style("  ⚠ No LLM backend configured.", fg="yellow"))
        click.echo("    Set LM_STUDIO_URL, OLLAMA_URL, or ANTHROPIC_API_KEY to use LLM features.")

    click.echo()

    # ── Section 2: Embedding Model ──────────────────────────────────────
    click.echo(click.style("  [2/4] Embedding Model", fg="yellow", bold=True))
    click.echo()

    # Pick an embedding source.  Default to whichever provider serves
    # the local tier (so embeddings and chat live behind the same
    # runtime).  Override via the embedding_backend field.
    if config.embedding_backend:
        embed_choice = config.embedding_backend
    elif config.local_backend == "lmstudio" and lm_studio_found:
        embed_choice = "openai-compatible"
    elif config.local_backend == "ollama" and ollama_found:
        embed_choice = "ollama"
    elif lm_studio_found and not ollama_found:
        embed_choice = "openai-compatible"
    elif ollama_found and not lm_studio_found:
        embed_choice = "ollama"
    elif lm_studio_found:
        embed_choice = "openai-compatible"
    elif ollama_found:
        embed_choice = "ollama"
    else:
        embed_choice = None

    if embed_choice == "openai-compatible":
        # LM Studio: surface any loaded embedding models we found.
        embed_models = [m for m in lm_studio_models if _looks_like_embedding_model(m)]
        default_model = (
            config.embedding_model
            if config.embedding_model and config.embedding_model != "nomic-embed-text"
            else (embed_models[0] if embed_models else "text-embedding-nomic-embed-text-v1.5")
        )
        if embed_models:
            click.echo(
                click.style(
                    f"  ✓ LM Studio embedding model(s) loaded: {', '.join(embed_models[:5])}",
                    fg="green",
                )
            )
        else:
            click.echo(
                click.style(
                    "  ! No embedding model loaded in LM Studio yet — "
                    "load one (e.g. nomic-embed-text-v1.5) before ingesting.",
                    fg="yellow",
                )
            )
        if not non_interactive:
            default_model = click.prompt("    Embedding model", default=default_model)
        config.embedding_model = default_model
        config.embedding_backend = "openai-compatible"
    elif embed_choice == "ollama":
        has_embed = any(config.embedding_model in m for m in ollama_models)
        if has_embed:
            click.echo(click.style(f"  ✓ {config.embedding_model} available", fg="green"))
        else:
            click.echo(click.style(f"  ✗ {config.embedding_model} not found", fg="red"))
            if not non_interactive and click.confirm(
                f"    Pull {config.embedding_model}?", default=True
            ):
                click.echo(f"    Pulling {config.embedding_model}... (may take a few minutes)")
                _pull_embedding_model(probe_url, config.embedding_model)

        if not non_interactive:
            custom_model = click.prompt("    Embedding model", default=config.embedding_model)
            config.embedding_model = custom_model
        config.embedding_backend = "ollama"
    else:
        click.echo("  Skipped (no local LLM runtime detected)")

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

    click.echo(f"    LM Studio:    {config.lm_studio_url or 'not configured'}")
    click.echo(f"    Ollama:       {config.ollama_url or 'not configured'}")
    click.echo(f"    Local tier:   {config.local_backend or 'auto'}")
    if config.anthropic_api_key:
        masked = config.anthropic_api_key[:7] + "..." + config.anthropic_api_key[-4:]
        click.echo(f"    Anthropic:    {masked}")
    else:
        click.echo("    Anthropic:    not configured")
    click.echo(f"    Embeddings:   {config.embedding_model} ({config.embedding_backend or 'n/a'})")
    click.echo(f"    Data dir:     {config.rag_data_dir or 'not set'}")
    click.echo(f"    Vector store: {config.rag_vector_store}")
    click.echo()

    save_config(config, config_path)
    click.echo(click.style(f"  ✓ Config saved to {expanded_path}", fg="green"))
    click.echo()

    # Next steps
    click.echo(click.style("  Next steps:", fg="cyan", bold=True))
    if config.rag_data_dir:
        click.echo(f"    heddle rag ingest {config.rag_data_dir}/result*.json")
    else:
        click.echo("    heddle rag ingest /path/to/telegram/exports/*.json")
    click.echo('    heddle rag search "your query here"')
    click.echo("    heddle rag serve")
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
