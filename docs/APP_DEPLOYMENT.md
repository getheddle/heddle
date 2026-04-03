# App Deployment Guide

**Heddle — Deploying Application Bundles**

---

## Overview

A Heddle **app** is a ZIP archive containing worker configs, pipeline configs,
and an optional Python package. Apps are deployed through the Workshop web UI
or programmatically via the `AppManager` class.

After deployment, running actors are notified to reload their configs via
the NATS control channel — no restart required.

---

## Manifest Format

Every app ZIP must contain a `manifest.yaml` at the root:

```yaml
name: "myapp"                         # Required. lowercase, hyphens, underscores
version: "1.0.0"                      # Required. Semantic version
description: "My Heddle application"    # Required. Human-readable
heddle_version: ">=0.4.0"              # Minimum heddle version

required_extras:                      # Heddle extras this app needs
  - duckdb
  - mcp

python_package:                       # Optional — for apps with Python code
  name: "myapp"
  install_path: "src/"

entry_configs:
  workers:
    - config: "configs/workers/my_worker.yaml"
      tier: "standard"
  pipelines:
    - config: "configs/orchestrators/my_pipeline.yaml"
  schedulers:
    - config: "configs/schedulers/my_schedule.yaml"
  mcp:
    - config: "configs/mcp/my_mcp.yaml"

scripts:
  - path: "scripts/setup.py"
    description: "Initial setup script"
```

---

## Building an App ZIP

### Using the build script

Both `baft` and `docman` include build scripts:

```bash
# Build baft app bundle
cd baft/
bash scripts/build-app.sh
# Output: dist/baft-0.2.0.zip

# Build docman app bundle
cd docman/
bash scripts/build-app.sh
# Output: dist/docman-0.4.0.zip
```

### Manual build

```bash
cd myapp/
zip -r dist/myapp-1.0.0.zip \
    manifest.yaml \
    configs/ \
    -x "*.pyc" "__pycache__/*"
```

---

## Deploying via Workshop

1. Start the Workshop: `heddle workshop --port 8080`
2. Navigate to **Apps** in the navigation bar
3. Upload your `.zip` file using the deploy form
4. The app's workers and pipelines appear in the Workers and Pipelines lists

### Hot Reload

After deployment, the Workshop publishes a reload message to
`heddle.control.reload`. Running actors re-read their configs from disk
without restart. This works for:

- Workers (TaskWorker, LLMWorker, ProcessorWorker)
- Pipeline orchestrators
- Dynamic orchestrators

---

## Apps with Python Packages

If your app includes a `python_package` field in the manifest, the Workshop
will log a warning after deployment with install instructions:

```text
This app includes Python package 'docman'.
Install it manually: pip install -e ~/.heddle/apps/docman/src/
```

The Workshop cannot auto-install packages because it may not have write
access to the Python environment. Install the package manually before
starting workers that depend on it.

---

## App Directory Structure

Deployed apps are extracted to `~/.heddle/apps/{app_name}/`:

```text
~/.heddle/apps/
  baft/
    manifest.yaml
    configs/
      workers/
      orchestrators/
      schedulers/
      mcp/
    scripts/
  docman/
    manifest.yaml
    configs/
    src/docman/
```

---

## Removing Apps

From the Workshop, navigate to the app detail page and click **Remove App**.
Or from the Apps list, click the **Remove** button.

This deletes the app directory and its configs. Running actors are notified
to reload (they will no longer find the removed configs).

---

*For local deployment setup, see [LOCAL_DEPLOYMENT.md](LOCAL_DEPLOYMENT.md).
For Workshop features, see [workshop.md](workshop.md).*
