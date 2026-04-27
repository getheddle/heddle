# Feedback — C-documentation-onboarding-CODE session

**Date:** 2026-04-26
**Source plan:** `session-starters/C-documentation-onboarding-CODE.md`
**Repo state at start:** Heddle v0.9.1, 2,075 tests (per plan)

## Tasks completed

| # | Task | Status |
|---|------|--------|
| 1 | LOOM backronym → "Config-driven multi-LLM workflows" | Done |
| 2 | README badge v0.9.0 → current; "All 19 commands" → "All 17 commands" | Done |
| 3 | drawio toolchain bootstrap — workflow + dir + placeholder | Done (CI verification deferred — see below) |
| 4 | CSV + plain-text RAG ingestion (code, CLI, tests, docs) | Done |
| 5 | README "Three Ways to Use Heddle" command verification | Done — all four commands match current `--help` |
| Final | Version bump 0.9.1 → 0.9.2, README badge to match | Done |

## Test count delta

- Baseline (per plan): 2,075
- After this session: **2,102 collected** (2,100 passing, 2 failing — see "Pre-existing failures" below)
- Net new tests added: 30 (CSV ingestor: 14, plain-text ingestor: 11, CLI routing: 5)

## Lint

- `uv run ruff check src/ tests/` → all checks passed.

## Notable decisions for Chat to be aware of

### Test layout
Plan asked for `tests/contrib/rag/ingestion/test_csv_ingestor.py` etc., but the
existing convention under `tests/contrib/rag/` is **flat** (no `ingestion/`
sub-directory). I matched the existing convention rather than introducing a
new sub-tree. Files are at:

- `tests/contrib/rag/test_csv_ingestor.py`
- `tests/contrib/rag/test_text_ingestor.py`

### CLI test class name
The CLI routing tests live in the existing `tests/test_cli_rag.py` (extended
the file rather than creating a new one). Five new tests were added; the
existing `test_rag_ingest_help` was tightened to assert the new help text.

### CsvIngestor / PlainTextIngestor synthetic channel id
Both ingestors use `int.from_bytes(sha256(path)[:8], 'big') & 0x7FFFFFFFFFFFFFFF`
to produce a stable per-source channel id. This is **deterministic per
resolved path** (re-loading the same file yields the same id), which keeps
`merge_from_ingestors` happy without forcing it to know about non-Telegram
sources. There is a `test_channel_id_stable_per_path` test pinning this
behaviour.

### Encoding fallback
On `UnicodeDecodeError`, both ingestors log a warning and re-read the file
with `errors="replace"`. This matches the spec ("try UTF-8 first, fall back
to UTF-8 with `errors='replace'` and log a warning").

### Workshop-ui.svg
The plan only flagged the `LOOM WORKSHOP` text on line 10. The same SVG
also has a stale `Loom Workshop — UI Overview` title on line 7. Left as-is
since it was out of scope; flagging here so a future session can sweep it.

## Task 3 (drawio) — CI verification deferred

The workflow file, `docs/diagrams/README.md`, and a 3-box-and-2-arrows
placeholder `_pipeline-test.drawio` are all committed locally. Verifying
the pipeline end-to-end requires:

1. Pushing the branch to GitHub
2. Watching the `Build diagrams` Action on a PR or push to main
3. Confirming `docs/images/_pipeline-test.svg` is auto-committed

I added `permissions: contents: write` to the workflow (required by
`stefanzweifel/git-auto-commit-action@v5` on most repos). Worth confirming
that `Settings → Actions → General → Workflow permissions` is set to
"Read and write" or that the workflow's explicit permissions block is
honoured.

## Pre-existing failures (not from this session)

`uv run pytest tests/ -m "not integration and not deepeval"` reports two
failures unrelated to anything I touched:

1. `tests/test_mdns.py::TestHeddleServiceAdvertiser::test_register_resolves_default_host`
   — DNS resolution test, fails on this machine regardless of branch.
2. `tests/test_workshop_app.py::TestDetectAvailableBackends::test_no_backends_when_no_env_vars`
   — fails because LM Studio is reachable from the test process; the
   monkeypatch removes env vars but the workshop's backend detection
   still picks up a running LM Studio at `localhost:1234`. Likely a test
   isolation issue worth a follow-up.

Both failures reproduce on a clean checkout (verified with `git stash`).

## Touched files

```text
M  CLAUDE.md
M  GOVERNANCE.md
M  README.md
M  docs/ARCHITECTURE.md
M  docs/GETTING_STARTED.md
M  docs/KUBERNETES.md
M  docs/LOCAL_DEPLOYMENT.md
M  docs/images/workshop-ui.svg
M  docs/rag-howto.md
M  pyproject.toml
M  src/heddle/__init__.py
M  src/heddle/cli/main.py
M  src/heddle/cli/rag.py
M  tests/test_cli_rag.py
A  .github/workflows/build-diagrams.yml
A  docs/diagrams/README.md
A  docs/diagrams/_pipeline-test.drawio
A  src/heddle/contrib/rag/ingestion/csv_ingestor.py
A  src/heddle/contrib/rag/ingestion/text_ingestor.py
A  tests/contrib/rag/test_csv_ingestor.py
A  tests/contrib/rag/test_text_ingestor.py
A  FEEDBACK.md
```

(`docs/index.md`, `docs/batch-processing.md`, and `mkdocs.yml` show as
modified in `git status` but those changes pre-existed and were not
touched in this session.)
