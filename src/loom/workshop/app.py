"""
Workshop web application — FastAPI + HTMX + Jinja2.

Entry point: ``create_app()`` returns a configured FastAPI application.
Start via CLI: ``loom workshop --port 8080``
"""

from __future__ import annotations

import json
from pathlib import Path

import structlog
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from loom.worker.backends import build_backends_from_env
from loom.workshop.config_manager import ConfigManager
from loom.workshop.db import WorkshopDB
from loom.workshop.eval_runner import EvalRunner
from loom.workshop.pipeline_editor import PipelineEditor
from loom.workshop.test_runner import WorkerTestRunner

logger = structlog.get_logger()

# Paths relative to this file
_THIS_DIR = Path(__file__).parent
_TEMPLATES_DIR = _THIS_DIR / "templates"
_STATIC_DIR = _THIS_DIR / "static"


def create_app(  # noqa: PLR0915
    configs_dir: str = "configs/",
    db_path: str = "~/.loom/workshop.duckdb",
    nats_url: str | None = None,  # noqa: ARG001
) -> FastAPI:
    """Create the Workshop FastAPI application.

    Args:
        configs_dir: Root directory containing ``workers/`` and ``orchestrators/``.
        db_path: DuckDB database path (``~`` is expanded).
        nats_url: Optional NATS URL for live metrics (reserved for future use).
    """
    app = FastAPI(title="Loom Workshop", docs_url=None, redoc_url=None)

    # Static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Templates
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

    # Initialize components
    db = WorkshopDB(db_path)
    backends = build_backends_from_env()
    test_runner = WorkerTestRunner(backends)
    eval_runner = EvalRunner(test_runner, db)
    config_mgr = ConfigManager(configs_dir, db)

    logger.info(
        "workshop.initialized",
        configs_dir=configs_dir,
        db_path=db_path,
        backends=list(backends.keys()),
    )

    # ------------------------------------------------------------------
    # Routes
    # ------------------------------------------------------------------

    @app.get("/", response_class=RedirectResponse)
    async def root():
        return RedirectResponse(url="/workers")

    @app.get("/health")
    async def health():
        return {"status": "ok", "backends": list(backends.keys())}

    # --- Workers ---

    @app.get("/workers", response_class=HTMLResponse)
    async def workers_list(request: Request):
        workers = config_mgr.list_workers()
        return templates.TemplateResponse(
            "workers/list.html",
            {
                "request": request,
                "workers": workers,
            },
        )

    @app.get("/workers/{name}", response_class=HTMLResponse)
    async def worker_detail(request: Request, name: str):
        try:
            config = config_mgr.get_worker(name)
            yaml_content = config_mgr.get_worker_yaml(name)
        except FileNotFoundError:
            return HTMLResponse("Worker not found", status_code=404)
        versions = config_mgr.get_worker_version_history(name)
        return templates.TemplateResponse(
            "workers/detail.html",
            {
                "request": request,
                "config": config,
                "yaml_content": yaml_content,
                "name": name,
                "versions": versions,
            },
        )

    @app.post("/workers/{name}", response_class=HTMLResponse)
    async def worker_save(request: Request, name: str):
        form = await request.form()
        import yaml

        try:
            config = yaml.safe_load(form["yaml_content"])
        except Exception as e:
            return HTMLResponse(f"Invalid YAML: {e}", status_code=400)
        errors = config_mgr.save_worker(name, config, description=form.get("description"))
        if errors:
            return HTMLResponse(f"Validation errors: {'; '.join(errors)}", status_code=400)
        return RedirectResponse(url=f"/workers/{name}", status_code=303)

    @app.post("/workers/{name}/clone", response_class=RedirectResponse)
    async def worker_clone(request: Request, name: str):
        form = await request.form()
        new_name = form["new_name"]
        errors = config_mgr.clone_worker(name, new_name)
        if errors:
            return HTMLResponse(f"Clone failed: {'; '.join(errors)}", status_code=400)
        return RedirectResponse(url=f"/workers/{new_name}", status_code=303)

    # --- Test Bench ---

    @app.get("/workers/{name}/test", response_class=HTMLResponse)
    async def worker_test(request: Request, name: str):
        try:
            config = config_mgr.get_worker(name)
        except FileNotFoundError:
            return HTMLResponse("Worker not found", status_code=404)
        return templates.TemplateResponse(
            "workers/test.html",
            {
                "request": request,
                "config": config,
                "name": name,
                "available_tiers": list(backends.keys()),
            },
        )

    @app.post("/workers/{name}/test/run", response_class=HTMLResponse)
    async def worker_test_run(request: Request, name: str):
        form = await request.form()
        try:
            config = config_mgr.get_worker(name)
            payload = json.loads(form["payload"])
            tier = form.get("tier") or None
        except FileNotFoundError:
            return HTMLResponse("Worker not found", status_code=404)
        except json.JSONDecodeError as e:
            return templates.TemplateResponse(
                "partials/test_result.html",
                {
                    "request": request,
                    "error": f"Invalid JSON payload: {e}",
                },
            )

        result = await test_runner.run(config, payload, tier=tier)
        return templates.TemplateResponse(
            "partials/test_result.html",
            {
                "request": request,
                "result": result,
            },
        )

    # --- Eval ---

    @app.get("/workers/{name}/eval", response_class=HTMLResponse)
    async def worker_eval(request: Request, name: str):
        try:
            config = config_mgr.get_worker(name)
        except FileNotFoundError:
            return HTMLResponse("Worker not found", status_code=404)
        runs = db.get_eval_runs(name)
        return templates.TemplateResponse(
            "workers/eval.html",
            {
                "request": request,
                "config": config,
                "name": name,
                "runs": runs,
                "available_tiers": list(backends.keys()),
            },
        )

    @app.post("/workers/{name}/eval/run", response_class=HTMLResponse)
    async def worker_eval_run(request: Request, name: str):
        form = await request.form()
        try:
            config = config_mgr.get_worker(name)
            import yaml

            suite = yaml.safe_load(form["test_suite"])
            if not isinstance(suite, list):
                raise ValueError("Test suite must be a YAML list")
            tier = form.get("tier") or None
            scoring = form.get("scoring", "field_match")
        except Exception as e:
            return HTMLResponse(f"Error: {e}", status_code=400)

        run_id = await eval_runner.run_suite(config, suite, tier=tier, scoring=scoring)
        return RedirectResponse(url=f"/workers/{name}/eval/{run_id}", status_code=303)

    @app.get("/workers/{name}/eval/{run_id}", response_class=HTMLResponse)
    async def worker_eval_detail(request: Request, name: str, run_id: str):
        runs = db.get_eval_runs(name)
        run = next((r for r in runs if r["id"] == run_id), None)
        if not run:
            return HTMLResponse("Eval run not found", status_code=404)
        results = db.get_eval_results(run_id)
        return templates.TemplateResponse(
            "workers/eval_detail.html",
            {
                "request": request,
                "name": name,
                "run": run,
                "results": results,
            },
        )

    # --- Pipelines ---

    @app.get("/pipelines", response_class=HTMLResponse)
    async def pipelines_list(request: Request):
        pipelines = config_mgr.list_pipelines()
        return templates.TemplateResponse(
            "pipelines/list.html",
            {
                "request": request,
                "pipelines": pipelines,
            },
        )

    @app.get("/pipelines/{name}", response_class=HTMLResponse)
    async def pipeline_detail(request: Request, name: str):
        try:
            config = config_mgr.get_pipeline(name)
        except FileNotFoundError:
            return HTMLResponse("Pipeline not found", status_code=404)
        graph = PipelineEditor.get_dependency_graph(config)
        workers = config_mgr.list_workers()
        return templates.TemplateResponse(
            "pipelines/editor.html",
            {
                "request": request,
                "config": config,
                "name": name,
                "graph": graph,
                "workers": workers,
            },
        )

    @app.post("/pipelines/{name}/stage", response_class=HTMLResponse)
    async def pipeline_stage_edit(request: Request, name: str):
        form = await request.form()
        action = form["action"]
        try:
            config = config_mgr.get_pipeline(name)

            if action == "insert":
                import yaml

                stage_def = yaml.safe_load(form["stage_yaml"])
                after = form.get("after_stage") or None
                config = PipelineEditor.insert_stage(config, stage_def, after)
            elif action == "remove":
                config = PipelineEditor.remove_stage(config, form["stage_name"])
            elif action == "swap":
                config = PipelineEditor.swap_worker(
                    config,
                    form["stage_name"],
                    form["new_worker_type"],
                    form.get("new_tier") or None,
                )
            elif action == "branch":
                import yaml

                stage_def = yaml.safe_load(form["stage_yaml"])
                config = PipelineEditor.add_parallel_branch(config, stage_def)

            errors = config_mgr.save_pipeline(name, config)
            if errors:
                return HTMLResponse(f"Validation errors: {'; '.join(errors)}", status_code=400)

        except (ValueError, FileNotFoundError) as e:
            return HTMLResponse(f"Error: {e}", status_code=400)

        return RedirectResponse(url=f"/pipelines/{name}", status_code=303)

    @app.get("/pipelines/{name}/graph", response_class=JSONResponse)
    async def pipeline_graph(name: str):
        try:
            config = config_mgr.get_pipeline(name)
        except FileNotFoundError:
            return JSONResponse({"error": "Not found"}, status_code=404)
        return PipelineEditor.get_dependency_graph(config)

    return app
