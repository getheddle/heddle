# Diagram sources

`.drawio` files in this directory are the source of truth for architecture
and concept diagrams. CI auto-exports them to SVG on every change.

## How it works

- `.drawio` files in this directory are exported to SVG by CI
  (`.github/workflows/build-diagrams.yml`)
- Exported SVGs land in `docs/images/` with `--embed-diagram` so they are
  re-openable in draw.io
- Edit `.drawio` files in draw.io desktop or the web editor at
  <https://app.diagrams.net>

## Adding a new diagram

1. Create or save the diagram as `docs/diagrams/<name>.drawio`
2. Open a PR — the workflow exports `docs/images/<name>.svg` and commits it
3. Reference the SVG from docs as `![Caption](images/<name>.svg)`

## Pipeline test diagram

`_pipeline-test.drawio` is a trivial 3-box-and-2-arrows diagram kept around
as the working example for contributors and to verify the export pipeline
still functions. Do not delete.
