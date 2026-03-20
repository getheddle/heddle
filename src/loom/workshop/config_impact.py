"""
Config impact analysis — show what breaks if a worker config changes.

Given a worker name, scans all pipeline configs to find stages that reference
it, maps downstream dependencies, and assesses breaking-change risk based on
output schema presence.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from loom.workshop.config_manager import ConfigManager

logger = structlog.get_logger()


def get_impact(worker_name: str, config_manager: ConfigManager) -> dict[str, Any]:
    """Analyze the impact of changing a worker config.

    Scans all pipeline configs to find:
    - Which pipelines reference this worker (by ``worker_type``)
    - Which stages use this worker
    - Which downstream stages depend on those stages
    - Whether the worker has an output_schema (breaking-change guard)

    Args:
        worker_name: The worker ``name`` field to search for.
        config_manager: ConfigManager with access to all configs.

    Returns:
        Dict with keys:
            ``worker_name``: The queried worker name.
            ``pipelines``: List of pipeline impact dicts, each with:
                ``name``: Pipeline name.
                ``stages``: List of stage dicts that use this worker.
                ``downstream``: List of stage names that depend on worker stages.
            ``total_pipelines``: Count of affected pipelines.
            ``total_stages``: Count of affected stages.
            ``total_downstream``: Count of downstream stages.
            ``has_output_schema``: Whether the worker config declares output_schema.
            ``risk``: ``"high"`` if downstream stages exist, else ``"low"``.
    """
    pipelines = config_manager.list_pipelines()
    affected_pipelines: list[dict[str, Any]] = []
    total_stages = 0
    total_downstream = 0

    for pipeline_info in pipelines:
        try:
            pipeline_cfg = config_manager.get_pipeline(pipeline_info["name"])
        except (FileNotFoundError, Exception) as exc:
            logger.debug("impact.pipeline_load_failed", name=pipeline_info["name"], error=str(exc))
            continue

        stages = pipeline_cfg.get("pipeline_stages", [])
        if not stages:
            continue

        # Find stages that use this worker.
        worker_stages = [s for s in stages if s.get("worker_type") == worker_name]
        if not worker_stages:
            continue

        worker_stage_names = {s["name"] for s in worker_stages}

        # Infer dependencies to find downstream stages.
        deps = _infer_dependencies(stages)
        downstream = _find_downstream(worker_stage_names, deps)

        affected_pipelines.append(
            {
                "name": pipeline_cfg.get("name", pipeline_info["name"]),
                "stages": [
                    {
                        "name": s["name"],
                        "tier": s.get("tier", "local"),
                        "has_input_schema": "input_schema" in s,
                        "has_output_schema": "output_schema" in s,
                    }
                    for s in worker_stages
                ],
                "downstream": sorted(downstream),
            }
        )
        total_stages += len(worker_stages)
        total_downstream += len(downstream)

    # Check worker output_schema.
    has_output_schema = False
    try:
        worker_cfg = config_manager.get_worker(worker_name)
        has_output_schema = bool(worker_cfg.get("output_schema"))
    except FileNotFoundError:
        pass

    risk = "high" if total_downstream > 0 else "low"

    return {
        "worker_name": worker_name,
        "pipelines": affected_pipelines,
        "total_pipelines": len(affected_pipelines),
        "total_stages": total_stages,
        "total_downstream": total_downstream,
        "has_output_schema": has_output_schema,
        "risk": risk,
    }


def _infer_dependencies(stages: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Infer stage dependencies from input_mapping paths.

    Mirrors ``PipelineOrchestrator._infer_dependencies()`` logic.
    """
    stage_names = {s["name"] for s in stages}
    deps: dict[str, set[str]] = {}

    for stage in stages:
        name = stage["name"]
        if "depends_on" in stage:
            deps[name] = {d for d in stage["depends_on"] if d in stage_names}
            continue
        mapping = stage.get("input_mapping", {})
        inferred: set[str] = set()
        for source_path in mapping.values():
            first_segment = source_path.split(".")[0]
            if first_segment != "goal" and first_segment in stage_names:
                inferred.add(first_segment)
        deps[name] = inferred

    return deps


def _find_downstream(
    source_stages: set[str],
    deps: dict[str, set[str]],
) -> set[str]:
    """Find all stages transitively downstream of the given source stages.

    A stage is downstream if it depends (directly or transitively) on any
    of the source stages.
    """
    # Build reverse adjacency: stage -> set of stages that depend on it.
    dependents: dict[str, set[str]] = {}
    for stage, dep_set in deps.items():
        for dep in dep_set:
            dependents.setdefault(dep, set()).add(stage)

    # BFS from source stages through dependents.
    visited: set[str] = set()
    queue = list(source_stages)

    while queue:
        current = queue.pop(0)
        for dependent in dependents.get(current, set()):
            if dependent not in visited and dependent not in source_stages:
                visited.add(dependent)
                queue.append(dependent)

    return visited
