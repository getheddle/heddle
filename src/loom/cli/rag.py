"""
Zero-config RAG pipeline CLI.

Runs the full RAG pipeline directly — no NATS, no router, no worker actors.
Uses classes from loom.contrib.rag with sensible defaults.

Commands::

    loom rag ingest <paths>...   # Ingest Telegram JSON exports
    loom rag search <query>      # Semantic search
    loom rag stats               # Store statistics
    loom rag serve               # Start Workshop with RAG dashboard
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import click

from loom.cli.config import DEFAULT_CONFIG_PATH, LoomConfig, resolve_config

# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------


def _resolve_store_class(config: LoomConfig) -> str:
    """Return the dotted class path for the configured vector store."""
    if config.rag_vector_store == "lancedb":
        return "loom.contrib.lancedb.store.LanceDBVectorStore"
    return "loom.contrib.rag.vectorstore.duckdb_store.DuckDBVectorStore"


def _open_store(config: LoomConfig) -> Any:
    """Instantiate and initialize a VectorStore from config."""
    import importlib

    class_path = _resolve_store_class(config)
    module_path, class_name = class_path.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)

    db_path = str(Path(config.rag_db_path).expanduser())
    store = cls(
        db_path=db_path,
        embedding_model=config.embedding_model,
        ollama_url=config.ollama_url or "http://localhost:11434",
    )
    return store.initialize()


# ---------------------------------------------------------------------------
# RAG command group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--config-path", default=DEFAULT_CONFIG_PATH, help="Config file path.")
@click.option("--db-path", default=None, help="Override vector store path.")
@click.option("--store", default=None, type=click.Choice(["duckdb", "lancedb"]))
@click.option("--ollama-url", default=None, help="Override Ollama URL.")
@click.option("--embedding-model", default=None, help="Override embedding model.")
@click.pass_context
def rag(
    ctx: click.Context,
    config_path: str,
    db_path: str | None,
    store: str | None,
    ollama_url: str | None,
    embedding_model: str | None,
) -> None:
    """RAG pipeline — ingest, search, and serve. No NATS needed."""
    overrides: dict[str, Any] = {}
    if db_path:
        overrides["rag_db_path"] = db_path
    if store:
        overrides["rag_vector_store"] = store
    if ollama_url:
        overrides["ollama_url"] = ollama_url
    if embedding_model:
        overrides["embedding_model"] = embedding_model
    ctx.ensure_object(dict)
    ctx.obj["config"] = resolve_config(cli_overrides=overrides, config_path=config_path)


# ---------------------------------------------------------------------------
# loom rag ingest
# ---------------------------------------------------------------------------


@rag.command()
@click.argument("paths", nargs=-1, required=True, type=click.Path(exists=True))
@click.option("--embed/--no-embed", default=True, help="Generate embeddings via Ollama.")
@click.option("--window-hours", default=6, type=int, help="Time window size in hours.")
@click.option("--chunk-target", default=400, type=int, help="Target chunk size in chars.")
@click.option("--chunk-max", default=600, type=int, help="Maximum chunk size in chars.")
@click.pass_context
def ingest(  # noqa: PLR0915
    ctx: click.Context,
    paths: tuple[str, ...],
    embed: bool,
    window_hours: int,
    chunk_target: int,
    chunk_max: int,
) -> None:
    """Ingest Telegram JSON exports into the vector store."""
    from datetime import timedelta

    from loom.contrib.rag.chunker.sentence_chunker import ChunkConfig, chunk_mux_entry
    from loom.contrib.rag.ingestion.telegram_ingestor import TelegramIngestor
    from loom.contrib.rag.mux.stream_mux import merge_from_ingestors
    from loom.contrib.rag.schemas.mux import MuxWindowConfig

    config: LoomConfig = ctx.obj["config"]

    click.echo()
    click.echo(click.style("  Loom RAG — Ingest", fg="cyan", bold=True))
    click.echo()

    # Step 1: Ingest
    click.echo("  [1/4] Loading Telegram exports...")
    ingestors = []
    for path in paths:
        t0 = time.perf_counter()
        ingestor = TelegramIngestor(path, min_text_len=10).load()
        posts = ingestor.ingest_all()
        elapsed = time.perf_counter() - t0
        click.echo(f"    {ingestor.channel_name:<30} {len(posts):>5} posts  ({elapsed:.2f}s)")
        ingestors.append(ingestor)

    if not ingestors:
        raise click.ClickException("No valid exports found.")

    # Step 2: Multiplex
    click.echo(f"\n  [2/4] Multiplexing ({window_hours}h windows)...")
    t0 = time.perf_counter()
    window_config = MuxWindowConfig(window_duration=timedelta(hours=window_hours))
    stream = merge_from_ingestors(ingestors, window_config=window_config)
    elapsed = time.perf_counter() - t0
    click.echo(
        f"    {stream.total_entries} entries, {len(stream.window_ids)} windows, "
        f"{stream.channel_count} channels  ({elapsed:.3f}s)"
    )

    # Step 3: Chunk
    click.echo(f"\n  [3/4] Chunking (target={chunk_target}, max={chunk_max})...")
    chunk_cfg = ChunkConfig(target_chars=chunk_target, max_chars=chunk_max)
    all_chunks = []
    t0 = time.perf_counter()
    for entry in stream.entries:
        all_chunks.extend(chunk_mux_entry(entry, config=chunk_cfg))
    elapsed = time.perf_counter() - t0
    avg_len = sum(len(c.text) for c in all_chunks) / max(len(all_chunks), 1)
    click.echo(f"    {len(all_chunks)} chunks, avg {avg_len:.0f} chars  ({elapsed:.3f}s)")

    # Step 4: Store
    db_path_display = str(Path(config.rag_db_path).expanduser())
    click.echo(f"\n  [4/4] Storing in {config.rag_vector_store} ({db_path_display})...")

    if embed:
        store = _open_store(config)
        t0 = time.perf_counter()
        count = store.add_chunks(all_chunks, batch_size=64)
        elapsed = time.perf_counter() - t0
        click.echo(f"    Embedded & stored: {count} chunks ({elapsed:.1f}s)")
        store.close()
    else:
        from loom.contrib.rag.schemas.embedding import EmbeddedChunk

        store = _open_store(config)
        embedded = [
            EmbeddedChunk(
                chunk_id=c.chunk_id,
                source_global_id=c.source_global_id,
                source_channel_id=c.source_channel_id,
                text=c.text,
                embedding=[],
                model="none",
                dimensions=0,
            )
            for c in all_chunks
        ]
        t0 = time.perf_counter()
        count = store.add_embedded_chunks(embedded)
        elapsed = time.perf_counter() - t0
        click.echo(f"    Stored (no embeddings): {count} chunks ({elapsed:.1f}s)")
        click.echo("    Tip: Use --embed to generate embeddings via Ollama")
        store.close()

    # Summary
    click.echo()
    click.echo(
        click.style(
            f"  ✓ {stream.channel_count} channels → {stream.total_entries} posts → "
            f"{len(all_chunks)} chunks → {config.rag_vector_store}",
            fg="green",
        )
    )
    click.echo()


# ---------------------------------------------------------------------------
# loom rag search
# ---------------------------------------------------------------------------


@rag.command()
@click.argument("query")
@click.option("--limit", "-n", default=10, type=int, help="Max results.")
@click.option("--min-score", default=0.0, type=float, help="Minimum similarity score.")
@click.pass_context
def search(ctx: click.Context, query: str, limit: int, min_score: float) -> None:
    """Search the vector store."""
    config: LoomConfig = ctx.obj["config"]
    store = _open_store(config)

    try:
        results = store.search(query, limit=limit, min_score=min_score)
    finally:
        store.close()

    if not results:
        click.echo("No results found.")
        return

    click.echo()
    click.echo(click.style(f"  {len(results)} result(s) for: {query}", fg="cyan", bold=True))
    click.echo()

    for i, r in enumerate(results, 1):
        score_color = "green" if r.score >= 0.7 else "yellow" if r.score >= 0.4 else "red"
        click.echo(click.style(f"  [{r.score:.3f}]", fg=score_color) + f"  #{i}")
        click.echo(f"    Source: {r.source_global_id}  Channel: {r.source_channel_id}")
        # Truncate text to 200 chars for display
        text = r.text.replace("\n", " ")
        if len(text) > 200:
            text = text[:200] + "..."
        click.echo(f"    {text}")
        click.echo()


# ---------------------------------------------------------------------------
# loom rag stats
# ---------------------------------------------------------------------------


@rag.command()
@click.pass_context
def stats(ctx: click.Context) -> None:
    """Show vector store statistics."""
    config: LoomConfig = ctx.obj["config"]
    store = _open_store(config)

    try:
        store_stats = store.stats()
    finally:
        store.close()

    click.echo()
    click.echo(click.style("  Vector Store Statistics", fg="cyan", bold=True))
    click.echo(f"  Store: {config.rag_vector_store} ({config.rag_db_path})")
    click.echo()

    for k, v in store_stats.items():
        click.echo(f"    {k}: {v}")
    click.echo()


# ---------------------------------------------------------------------------
# loom rag serve
# ---------------------------------------------------------------------------


@rag.command()
@click.option("--port", default=8080, type=int, help="Workshop port.")
@click.option("--host", default="127.0.0.1", help="Bind address.")
@click.pass_context
def serve(ctx: click.Context, port: int, host: str) -> None:
    """Start Workshop with RAG dashboard pre-configured."""
    config: LoomConfig = ctx.obj["config"]

    # Apply config to env so build_backends_from_env() picks up keys
    from loom.cli.config import apply_config_to_env

    apply_config_to_env(config)

    from loom.workshop.app import create_app

    store_class = _resolve_store_class(config) if config.rag_vector_store != "duckdb" else None

    app = create_app(
        rag_db_path=str(Path(config.rag_db_path).expanduser()),
        rag_store_class=store_class,
    )

    click.echo()
    click.echo(click.style("  Loom RAG — Workshop", fg="cyan", bold=True))
    click.echo(f"  Store: {config.rag_vector_store} ({config.rag_db_path})")
    click.echo(f"  URL:   http://{host}:{port}/rag")
    click.echo()

    import uvicorn

    uvicorn.run(app, host=host, port=port)
