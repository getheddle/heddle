"""
Tests for heddle rag command group — ingest, search, stats, serve.

All tests use Click's CliRunner with mocked RAG classes.
No external services needed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import structlog
from click.testing import CliRunner

_saved_structlog_config = structlog.get_config()
from heddle.cli.rag import rag  # noqa: E402

structlog.configure(**_saved_structlog_config)


# ---------------------------------------------------------------------------
# Help commands
# ---------------------------------------------------------------------------


def test_rag_help():
    """rag --help shows the group help."""
    result = CliRunner().invoke(rag, ["--help"])
    assert result.exit_code == 0
    assert "RAG pipeline" in result.output


def test_rag_ingest_help():
    """rag ingest --help shows usage."""
    result = CliRunner().invoke(rag, ["ingest", "--help"])
    assert result.exit_code == 0
    assert "Ingest Telegram JSON exports" in result.output


def test_rag_search_help():
    """rag search --help shows usage."""
    result = CliRunner().invoke(rag, ["search", "--help"])
    assert result.exit_code == 0
    assert "Search the vector store" in result.output


def test_rag_stats_help():
    """rag stats --help shows usage."""
    result = CliRunner().invoke(rag, ["stats", "--help"])
    assert result.exit_code == 0
    assert "vector store statistics" in result.output


def test_rag_serve_help():
    """rag serve --help shows usage."""
    result = CliRunner().invoke(rag, ["serve", "--help"])
    assert result.exit_code == 0
    assert "Workshop with RAG dashboard" in result.output


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_ingestor(channel_name="TestChannel", channel_id=123, num_posts=5):
    """Create a mock TelegramIngestor."""
    mock = MagicMock()
    mock.channel_name = channel_name
    mock.channel_id = channel_id

    posts = []
    for i in range(num_posts):
        post = MagicMock()
        post.global_id = f"{channel_id}:{i}"
        post.text_clean = f"Post {i} text content"
        posts.append(post)
    mock.ingest_all.return_value = posts
    mock.load.return_value = mock
    return mock


def _make_mock_stream(num_entries=5, num_windows=2, num_channels=1):
    """Create a mock MuxedStream."""
    stream = MagicMock()
    stream.total_entries = num_entries
    stream.channel_count = num_channels
    stream.window_ids = [f"w{i}" for i in range(num_windows)]

    entries = []
    for i in range(num_entries):
        entry = MagicMock()
        entry.channel_id = 123
        entry.text = f"Entry {i}"
        entries.append(entry)
    stream.entries = entries
    return stream


def _make_mock_chunks(num_chunks=10):
    """Create mock TextChunk objects."""
    chunks = []
    for i in range(num_chunks):
        chunk = MagicMock()
        chunk.chunk_id = f"123:{i}:0"
        chunk.source_global_id = f"123:{i}"
        chunk.source_channel_id = 123
        chunk.text = f"Chunk {i} text content here"
        chunks.append(chunk)
    return chunks


def _mock_ingest_patches(mock_store, mock_ingestor_factory=None, num_chunks=1):
    """Return a list of patch context managers for the ingest command.

    Because the ingest command uses lazy imports (inside function body),
    we patch at the source module level where the classes are defined.
    """
    if mock_ingestor_factory is None:
        mock_ingestor_factory = lambda *a, **kw: _make_mock_ingestor()  # noqa: E731

    return [
        patch(
            "heddle.contrib.rag.ingestion.telegram_ingestor.TelegramIngestor",
            side_effect=mock_ingestor_factory,
        ),
        patch(
            "heddle.contrib.rag.mux.stream_mux.merge_from_ingestors",
            return_value=_make_mock_stream(),
        ),
        patch(
            "heddle.contrib.rag.chunker.sentence_chunker.chunk_mux_entry",
            return_value=_make_mock_chunks(num_chunks),
        ),
        patch("heddle.cli.rag._open_store", return_value=mock_store),
    ]


# ---------------------------------------------------------------------------
# Ingest
# ---------------------------------------------------------------------------


def test_rag_ingest_single_file(tmp_path):
    """rag ingest processes a single Telegram export."""
    export = tmp_path / "result.json"
    export.write_text("{}")
    cfg_path = str(tmp_path / "config.yaml")

    mock_store = MagicMock()
    mock_store.add_embedded_chunks.return_value = 5

    patches = _mock_ingest_patches(mock_store)
    with patches[0], patches[1], patches[2], patches[3]:
        result = CliRunner().invoke(
            rag,
            [
                "--config-path",
                cfg_path,
                "ingest",
                "--no-embed",
                str(export),
            ],
        )

    assert result.exit_code == 0, result.output
    assert "TestChannel" in result.output
    assert "Stored" in result.output


def test_rag_ingest_with_embed(tmp_path):
    """rag ingest --embed calls add_chunks (not add_embedded_chunks)."""
    export = tmp_path / "result.json"
    export.write_text("{}")
    cfg_path = str(tmp_path / "config.yaml")

    mock_store = MagicMock()
    mock_store.add_chunks.return_value = 5

    patches = _mock_ingest_patches(mock_store)
    with patches[0], patches[1], patches[2], patches[3]:
        result = CliRunner().invoke(
            rag,
            [
                "--config-path",
                cfg_path,
                "ingest",
                "--embed",
                str(export),
            ],
        )

    assert result.exit_code == 0, result.output
    assert "Embedded & stored" in result.output
    mock_store.add_chunks.assert_called_once()


def test_rag_ingest_multiple_files(tmp_path):
    """rag ingest handles multiple files."""
    for i in range(3):
        (tmp_path / f"result-{i}.json").write_text("{}")
    cfg_path = str(tmp_path / "config.yaml")

    mock_store = MagicMock()
    mock_store.add_embedded_chunks.return_value = 15

    call_count = 0

    def make_ingestor(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return _make_mock_ingestor(channel_name=f"Channel{call_count}")

    patches = _mock_ingest_patches(mock_store, mock_ingestor_factory=make_ingestor)
    # Replace the stream mock to reflect 3 channels
    patches[1] = patch(
        "heddle.contrib.rag.mux.stream_mux.merge_from_ingestors",
        return_value=_make_mock_stream(num_entries=15, num_channels=3),
    )
    with patches[0], patches[1], patches[2], patches[3]:
        result = CliRunner().invoke(
            rag,
            [
                "--config-path",
                cfg_path,
                "ingest",
                "--no-embed",
                str(tmp_path / "result-0.json"),
                str(tmp_path / "result-1.json"),
                str(tmp_path / "result-2.json"),
            ],
        )

    assert result.exit_code == 0, result.output
    # All three channels were loaded
    assert "Channel1" in result.output
    assert "Channel2" in result.output
    assert "Channel3" in result.output
    assert "3 channels" in result.output


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------


def test_rag_search_prints_results(tmp_path):
    """rag search displays results with scores."""
    cfg_path = str(tmp_path / "config.yaml")

    mock_result = MagicMock()
    mock_result.score = 0.85
    mock_result.source_global_id = "123:42"
    mock_result.source_channel_id = 123
    mock_result.text = "Relevant result about earthquakes."

    mock_store = MagicMock()
    mock_store.search.return_value = [mock_result]
    mock_store.initialize.return_value = mock_store

    with patch("heddle.cli.rag._open_store", return_value=mock_store):
        result = CliRunner().invoke(
            rag,
            [
                "--config-path",
                cfg_path,
                "search",
                "earthquake",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "0.850" in result.output
    assert "earthquake" in result.output


def test_rag_search_empty_results(tmp_path):
    """rag search with no results prints a message."""
    cfg_path = str(tmp_path / "config.yaml")

    mock_store = MagicMock()
    mock_store.search.return_value = []
    mock_store.initialize.return_value = mock_store

    with patch("heddle.cli.rag._open_store", return_value=mock_store):
        result = CliRunner().invoke(
            rag,
            [
                "--config-path",
                cfg_path,
                "search",
                "nonexistent query",
            ],
        )

    assert result.exit_code == 0
    assert "No results found" in result.output


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------


def test_rag_stats_output(tmp_path):
    """rag stats prints store statistics."""
    cfg_path = str(tmp_path / "config.yaml")

    mock_store = MagicMock()
    mock_store.stats.return_value = {
        "total_chunks": 1500,
        "total_sources": 42,
    }
    mock_store.initialize.return_value = mock_store

    with patch("heddle.cli.rag._open_store", return_value=mock_store):
        result = CliRunner().invoke(
            rag,
            [
                "--config-path",
                cfg_path,
                "stats",
            ],
        )

    assert result.exit_code == 0, result.output
    assert "1500" in result.output
    assert "total_chunks" in result.output


# ---------------------------------------------------------------------------
# Serve
# ---------------------------------------------------------------------------


def test_rag_serve_starts_uvicorn(tmp_path):
    """rag serve calls uvicorn.run with the Workshop app."""
    cfg_path = str(tmp_path / "config.yaml")

    mock_app = MagicMock()
    with (
        patch("heddle.workshop.app.create_app", return_value=mock_app),
        patch("uvicorn.run") as mock_uvicorn_run,
    ):
        result = CliRunner().invoke(
            rag,
            [
                "--config-path",
                cfg_path,
                "serve",
                "--port",
                "9090",
                "--host",
                "0.0.0.0",
            ],
        )

    assert result.exit_code == 0, result.output
    mock_uvicorn_run.assert_called_once_with(mock_app, host="0.0.0.0", port=9090)


def test_rag_serve_passes_rag_params(tmp_path):
    """rag serve passes rag_db_path to create_app."""
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text("rag:\n  rag_db_path: /tmp/custom.duckdb\n")

    with (
        patch("heddle.workshop.app.create_app", return_value=MagicMock()) as mock_create,
        patch("uvicorn.run"),
    ):
        result = CliRunner().invoke(
            rag,
            [
                "--config-path",
                str(cfg_path),
                "serve",
            ],
        )

    assert result.exit_code == 0, result.output
    call_kwargs = mock_create.call_args[1]
    assert call_kwargs["rag_db_path"] == "/tmp/custom.duckdb"
