# Feedback — C-documentation-onboarding-CODE session

**Date:** 2026-04-26 → 2026-04-27 (push + CI loop)
**Source plan:** `session-starters/C-documentation-onboarding-CODE.md`
**Repo state at start:** Heddle v0.9.1, 2,075 tests (per plan)
**Repo state at end:** Heddle v0.9.2, 2,102 tests, all relevant CI green on `main`

## Tasks completed

| # | Task | Status |
|---|------|--------|
| 1 | LOOM backronym → "Config-driven multi-LLM workflows" | Done |
| 2 | README badge v0.9.0 → current; "All 19 commands" → "All 17 commands" | Done |
| 3 | drawio toolchain bootstrap — workflow + dir + placeholder | Done — CI verified end-to-end (see "Task 3 — CI run log") |
| 4 | CSV + plain-text RAG ingestion (code, CLI, tests, docs) | Done |
| 5 | README "Three Ways to Use Heddle" command verification | Done — all four commands match current `--help` |
| Final | Version bump 0.9.1 → 0.9.2, README badge to match | Done |

## Test count delta

- Baseline (per plan): 2,075
- After this session: **2,102 collected** (2,100 passing, 2 failing — see "Pre-existing failures" below)
- Net new tests added: 30 (CSV ingestor: 14, plain-text ingestor: 11, CLI routing: 5)

## Lint

- `uv run ruff check src/ tests/` → all checks passed.
- `uv run ruff format --check src/ tests/` → **was not run locally on the
  first pass; CI caught 5 files needing reformat.** Followed up with `ruff
  format` in commit `805155b`. Lesson for future sessions: include
  `ruff format --check` (or just `ruff format`) in the local pre-push
  checklist alongside `ruff check`.
- `rumdl check` → also not run locally on the first pass; caught 5
  blank-line-below-heading issues in `FEEDBACK.md`. Auto-fixed via
  `rumdl fmt` in the same `805155b` commit.

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

## Task 3 (drawio) — CI run log

Pipeline verified end-to-end on `main`. The first push surfaced two bugs
in the recipe the plan provided. Both fixed in follow-up commits:

1. **`embed: true` is not a valid input** on
   `rlespinasse/drawio-export-action@v2` — the actual input name is
   `embed-diagram: true`. The plan had `embed: true`; with that name,
   the action silently dropped the input and continued.
2. **The action's default `action-mode: auto` requires full git history**
   to compare against the previous push; with the default shallow
   checkout it errors out with "This is a shallow git repository.
   Add 'fetch-depth: 0' to 'actions/checkout' step." Added
   `fetch-depth: 0` to the checkout step.

After those two fixes (commit `37aa1c2`) plus the lint fixups (commit
`805155b`), `Build diagrams` ran clean and the
`stefanzweifel/git-auto-commit-action@v5` step pushed
`docs/images/_pipeline-test.svg` back to `main` as commit `9085d01`.

Both `_pipeline-test.drawio` (source) and `_pipeline-test.svg`
(generated) live in the tree as a working example for the next
contributor. They are scheduled for cleanup — see "Followups" below.

`permissions: contents: write` is on the workflow itself, so the
auto-commit step works without changing repo-level Actions permissions.

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

## Commits landed on `main`

```text
9085d01 chore(diagrams): auto-export drawio → svg          (auto-commit by CI)
805155b style: ruff format + rumdl fmt fixups for previous commit
37aa1c2 ci(diagrams): fix drawio-export-action inputs
ac810f4 chore: docs onboarding sweep, drawio toolchain, CSV/text RAG ingestion
```

Pushed directly to `main` per Hooman's explicit instruction ("you are
supposed to directly commit to main and push directly to verify CI").

## Followups

- **Scheduled cleanup routine** — A one-shot remote routine
  (`trig_01VAM9DHGUk7tGfXrK7MEz5C`) is set to fire on
  **2026-05-11T17:00:00Z** (Mon May 11, 10am PT). It will check whether
  any real `.drawio` files have been added to `docs/diagrams/` and, if
  so, open a PR removing `_pipeline-test.drawio`,
  `docs/images/_pipeline-test.svg`, and the "Pipeline test diagram"
  section of `docs/diagrams/README.md`. If no real diagrams exist by
  then, the routine reports back without making changes so we can
  extend the deadline.
- **`Loom Workshop — UI Overview` title on line 7 of
  `docs/images/workshop-ui.svg`** — out of scope for this session,
  flagged for a future sweep.
- **`test_workshop_app.py::test_no_backends_when_no_env_vars` test
  isolation** — the test passes only when LM Studio is not reachable;
  monkeypatching env vars isn't enough. Worth tightening the test or
  the `_detect_available_backends` function so detection is fully
  driven by the resolved config and not by ambient localhost
  reachability.

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
M  uv.lock
M  src/heddle/__init__.py
M  src/heddle/cli/main.py
M  src/heddle/cli/rag.py
M  tests/test_cli_rag.py
A  .github/workflows/build-diagrams.yml
A  docs/diagrams/README.md
A  docs/diagrams/_pipeline-test.drawio
A  docs/images/_pipeline-test.svg     (generated by CI in 9085d01)
A  src/heddle/contrib/rag/ingestion/csv_ingestor.py
A  src/heddle/contrib/rag/ingestion/text_ingestor.py
A  tests/contrib/rag/test_csv_ingestor.py
A  tests/contrib/rag/test_text_ingestor.py
A  FEEDBACK.md
```

`docs/index.md`, `docs/batch-processing.md`, and `mkdocs.yml` were
also pre-staged by Hooman before this session and were folded into
the same `ac810f4` commit at his request, but the content of those
files was not authored in this session.
