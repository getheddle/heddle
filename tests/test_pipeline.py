"""Test PipelineOrchestrator (unit tests, no infrastructure)."""

import asyncio

import pytest

from loom.bus.memory import InMemoryBus
from loom.core.messages import (
    OrchestratorGoal,
    TaskResult,
    TaskStatus,
)
from loom.orchestrator.pipeline import PipelineOrchestrator

# --- _resolve_path tests ---


class TestResolvePath:
    def test_simple_path(self):
        ctx = {"goal": {"context": {"file_ref": "report.pdf"}}}
        assert PipelineOrchestrator._resolve_path("goal.context.file_ref", ctx) == "report.pdf"

    def test_nested_output(self):
        ctx = {"extract": {"output": {"page_count": 42}}}
        assert PipelineOrchestrator._resolve_path("extract.output.page_count", ctx) == 42

    def test_top_level_key(self):
        ctx = {"extract": {"output": {"text": "hello"}}}
        result = PipelineOrchestrator._resolve_path("extract", ctx)
        assert result == {"output": {"text": "hello"}}

    def test_missing_key_raises(self):
        ctx = {"extract": {"output": {}}}
        with pytest.raises(KeyError, match="not found"):
            PipelineOrchestrator._resolve_path("extract.output.missing_field", ctx)

    def test_traverse_non_dict_raises(self):
        ctx = {"extract": {"output": "not_a_dict"}}
        with pytest.raises(ValueError, match="cannot traverse"):
            PipelineOrchestrator._resolve_path("extract.output.field", ctx)

    def test_array_value(self):
        ctx = {"extract": {"output": {"sections": ["intro", "body", "conclusion"]}}}
        assert PipelineOrchestrator._resolve_path("extract.output.sections", ctx) == [
            "intro",
            "body",
            "conclusion",
        ]

    def test_boolean_value(self):
        ctx = {"extract": {"output": {"has_tables": True}}}
        assert PipelineOrchestrator._resolve_path("extract.output.has_tables", ctx) is True


# --- _evaluate_condition tests ---


class TestEvaluateCondition:
    def test_equals_true(self):
        ctx = {"extract": {"output": {"has_tables": True}}}
        assert (
            PipelineOrchestrator._evaluate_condition("extract.output.has_tables == true", ctx)
            is True
        )

    def test_equals_false(self):
        ctx = {"extract": {"output": {"has_tables": False}}}
        assert (
            PipelineOrchestrator._evaluate_condition("extract.output.has_tables == true", ctx)
            is False
        )

    def test_not_equals_none(self):
        ctx = {"extract": {"output": {"data": "something"}}}
        assert PipelineOrchestrator._evaluate_condition("extract.output.data != null", ctx) is True

    def test_equals_none(self):
        ctx = {"extract": {"output": {"data": None}}}
        assert PipelineOrchestrator._evaluate_condition("extract.output.data == null", ctx) is True

    def test_missing_path_returns_false(self):
        ctx = {"extract": {"output": {}}}
        assert (
            PipelineOrchestrator._evaluate_condition("extract.output.nonexistent == true", ctx)
            is False
        )

    def test_invalid_condition_defaults_true(self):
        ctx = {}
        assert PipelineOrchestrator._evaluate_condition("invalid", ctx) is True

    def test_string_comparison(self):
        ctx = {"classify": {"output": {"document_type": "invoice"}}}
        assert (
            PipelineOrchestrator._evaluate_condition(
                "classify.output.document_type == invoice", ctx
            )
            is True
        )


# --- _build_stage_payload tests ---


class TestBuildStagePayload:
    def _make_orchestrator(self, tmp_path):
        """Create a PipelineOrchestrator with minimal config."""
        import yaml

        config = {
            "name": "test_pipeline",
            "pipeline_stages": [],
            "timeout_seconds": 10,
        }
        config_file = tmp_path / "pipeline.yaml"
        config_file.write_text(yaml.dump(config))
        return PipelineOrchestrator("test", str(config_file))

    def test_basic_mapping(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        context = {
            "goal": {"context": {"file_ref": "doc.pdf"}},
            "extract": {"output": {"page_count": 10, "text_preview": "hello"}},
        }
        stage = {
            "name": "classify",
            "worker_type": "doc_classifier",
            "input_mapping": {
                "text_preview": "extract.output.text_preview",
                "page_count": "extract.output.page_count",
            },
        }
        payload = orch._build_stage_payload(stage, context)
        assert payload == {"text_preview": "hello", "page_count": 10}

    def test_goal_context_mapping(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        context = {"goal": {"context": {"file_ref": "report.pdf"}}}
        stage = {
            "name": "extract",
            "worker_type": "doc_extractor",
            "input_mapping": {"file_ref": "goal.context.file_ref"},
        }
        payload = orch._build_stage_payload(stage, context)
        assert payload == {"file_ref": "report.pdf"}

    def test_missing_path_raises(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        context = {"goal": {"context": {}}}
        stage = {
            "name": "extract",
            "worker_type": "doc_extractor",
            "input_mapping": {"file_ref": "goal.context.file_ref"},
        }
        with pytest.raises(KeyError):
            orch._build_stage_payload(stage, context)

    def test_empty_mapping(self, tmp_path):
        orch = self._make_orchestrator(tmp_path)
        stage = {"name": "noop", "worker_type": "noop"}
        payload = orch._build_stage_payload(stage, {})
        assert payload == {}

    def test_cross_stage_mapping(self, tmp_path):
        """Output from one stage feeds into another."""
        orch = self._make_orchestrator(tmp_path)
        context = {
            "extract": {"output": {"file_ref": "extracted.json"}},
            "classify": {"output": {"document_type": "invoice"}},
        }
        stage = {
            "name": "summarize",
            "worker_type": "doc_summarizer",
            "input_mapping": {
                "file_ref": "extract.output.file_ref",
                "document_type": "classify.output.document_type",
            },
        }
        payload = orch._build_stage_payload(stage, context)
        assert payload == {"file_ref": "extracted.json", "document_type": "invoice"}


# --- _infer_dependencies tests ---


class TestInferDependencies:
    def test_goal_only_paths_have_no_deps(self):
        stages = [
            {"name": "extract", "input_mapping": {"file_ref": "goal.context.file_ref"}},
        ]
        deps = PipelineOrchestrator._infer_dependencies(stages)
        assert deps == {"extract": set()}

    def test_single_stage_dependency(self):
        stages = [
            {"name": "extract", "input_mapping": {"file_ref": "goal.context.file_ref"}},
            {"name": "classify", "input_mapping": {"text": "extract.output.text"}},
        ]
        deps = PipelineOrchestrator._infer_dependencies(stages)
        assert deps["extract"] == set()
        assert deps["classify"] == {"extract"}

    def test_multiple_dependencies(self):
        stages = [
            {"name": "A", "input_mapping": {"x": "goal.context.x"}},
            {"name": "B", "input_mapping": {"x": "goal.context.x"}},
            {"name": "C", "input_mapping": {"a": "A.output.a", "b": "B.output.b"}},
        ]
        deps = PipelineOrchestrator._infer_dependencies(stages)
        assert deps["C"] == {"A", "B"}

    def test_explicit_depends_on_overrides_inference(self):
        stages = [
            {"name": "A", "input_mapping": {"x": "goal.context.x"}},
            {"name": "B", "input_mapping": {"x": "goal.context.x"}},
            {
                "name": "C",
                "input_mapping": {"a": "A.output.a"},
                "depends_on": ["A", "B"],
            },
        ]
        deps = PipelineOrchestrator._infer_dependencies(stages)
        assert deps["C"] == {"A", "B"}

    def test_unknown_segments_ignored(self):
        stages = [
            {"name": "A", "input_mapping": {"x": "unknown_thing.output.x"}},
        ]
        deps = PipelineOrchestrator._infer_dependencies(stages)
        assert deps["A"] == set()

    def test_docman_pipeline_stays_sequential(self):
        """The docman 4-stage pipeline has fully sequential dependencies."""
        stages = [
            {"name": "extract", "input_mapping": {"file_ref": "goal.context.file_ref"}},
            {
                "name": "classify",
                "input_mapping": {
                    "text_preview": "extract.output.text_preview",
                    "page_count": "extract.output.page_count",
                },
            },
            {
                "name": "summarize",
                "input_mapping": {
                    "file_ref": "extract.output.file_ref",
                    "document_type": "classify.output.document_type",
                },
            },
            {
                "name": "ingest",
                "input_mapping": {
                    "source_file": "goal.context.file_ref",
                    "file_ref": "extract.output.file_ref",
                    "document_type": "classify.output.document_type",
                    "summary": "summarize.output.summary",
                },
            },
        ]
        deps = PipelineOrchestrator._infer_dependencies(stages)
        assert deps["extract"] == set()
        assert deps["classify"] == {"extract"}
        assert deps["summarize"] == {"extract", "classify"}
        assert deps["ingest"] == {"extract", "classify", "summarize"}

    def test_empty_input_mapping(self):
        stages = [{"name": "A"}]
        deps = PipelineOrchestrator._infer_dependencies(stages)
        assert deps["A"] == set()


# --- _build_execution_levels tests ---


class TestBuildExecutionLevels:
    def test_fully_sequential(self):
        stages = [
            {"name": "A"},
            {"name": "B"},
            {"name": "C"},
        ]
        deps = {"A": set(), "B": {"A"}, "C": {"B"}}
        levels = PipelineOrchestrator._build_execution_levels(stages, deps)
        assert len(levels) == 3
        assert [s["name"] for s in levels[0]] == ["A"]
        assert [s["name"] for s in levels[1]] == ["B"]
        assert [s["name"] for s in levels[2]] == ["C"]

    def test_two_independent_stages(self):
        stages = [
            {"name": "A"},
            {"name": "B"},
            {"name": "C"},
        ]
        deps = {"A": set(), "B": set(), "C": {"A", "B"}}
        levels = PipelineOrchestrator._build_execution_levels(stages, deps)
        assert len(levels) == 2
        assert [s["name"] for s in levels[0]] == ["A", "B"]  # alphabetical
        assert [s["name"] for s in levels[1]] == ["C"]

    def test_diamond_pattern(self):
        """A → B, A → C, B+C → D."""
        stages = [
            {"name": "A"},
            {"name": "B"},
            {"name": "C"},
            {"name": "D"},
        ]
        deps = {"A": set(), "B": {"A"}, "C": {"A"}, "D": {"B", "C"}}
        levels = PipelineOrchestrator._build_execution_levels(stages, deps)
        assert len(levels) == 3
        assert [s["name"] for s in levels[0]] == ["A"]
        assert [s["name"] for s in levels[1]] == ["B", "C"]
        assert [s["name"] for s in levels[2]] == ["D"]

    def test_circular_dependency_raises(self):
        stages = [{"name": "A"}, {"name": "B"}]
        deps = {"A": {"B"}, "B": {"A"}}
        with pytest.raises(ValueError, match="Circular dependency"):
            PipelineOrchestrator._build_execution_levels(stages, deps)

    def test_all_independent(self):
        stages = [{"name": "X"}, {"name": "Y"}, {"name": "Z"}]
        deps = {"X": set(), "Y": set(), "Z": set()}
        levels = PipelineOrchestrator._build_execution_levels(stages, deps)
        assert len(levels) == 1
        assert [s["name"] for s in levels[0]] == ["X", "Y", "Z"]

    def test_deterministic_ordering_within_level(self):
        """Stages within a level are sorted alphabetically."""
        stages = [{"name": "gamma"}, {"name": "alpha"}, {"name": "beta"}]
        deps = {"gamma": set(), "alpha": set(), "beta": set()}
        levels = PipelineOrchestrator._build_execution_levels(stages, deps)
        assert [s["name"] for s in levels[0]] == ["alpha", "beta", "gamma"]

    def test_docman_pipeline_produces_four_levels(self):
        """Docman's sequential pipeline → 4 levels of 1 stage each."""
        stages = [
            {"name": "extract"},
            {"name": "classify"},
            {"name": "summarize"},
            {"name": "ingest"},
        ]
        deps = {
            "extract": set(),
            "classify": {"extract"},
            "summarize": {"extract", "classify"},
            "ingest": {"extract", "classify", "summarize"},
        }
        levels = PipelineOrchestrator._build_execution_levels(stages, deps)
        assert len(levels) == 4
        for level in levels:
            assert len(level) == 1


# --- Parallel execution integration tests (InMemoryBus) ---


def _make_pipeline_orchestrator(tmp_path, stages, timeout=5, max_concurrent_goals=None):
    """Create a PipelineOrchestrator with given stages and InMemoryBus."""
    import yaml

    config = {
        "name": "test_pipeline",
        "pipeline_stages": stages,
        "timeout_seconds": timeout,
    }
    if max_concurrent_goals is not None:
        config["max_concurrent_goals"] = max_concurrent_goals
    config_file = tmp_path / "pipeline.yaml"
    config_file.write_text(yaml.dump(config))
    bus = InMemoryBus()
    orch = PipelineOrchestrator("test-pipeline", str(config_file), bus=bus)
    return orch, bus


async def _wait_for_pipeline_result(result_sub, goal_id, timeout=3):
    """Read messages from result_sub until we find the final pipeline result.

    The final result has task_id == goal_id (the pipeline publishes it with
    that convention).  Intermediate stage results also land on the same
    subject, so we skip those.
    """
    deadline = asyncio.get_event_loop().time() + timeout
    async for data in result_sub:
        if data.get("task_id") == goal_id:
            return data
        if asyncio.get_event_loop().time() > deadline:
            raise TimeoutError("Timed out waiting for pipeline result")
    raise TimeoutError("Subscription ended without pipeline result")


class TestParallelExecution:
    @pytest.mark.asyncio
    async def test_independent_stages_dispatch_concurrently(self, tmp_path):
        """Two independent stages should both be dispatched before either result arrives."""
        stages = [
            {
                "name": "A",
                "worker_type": "workerA",
                "tier": "local",
                "input_mapping": {"x": "goal.context.x"},
            },
            {
                "name": "B",
                "worker_type": "workerB",
                "tier": "local",
                "input_mapping": {"y": "goal.context.y"},
            },
            {
                "name": "C",
                "worker_type": "workerC",
                "tier": "local",
                "input_mapping": {"a": "A.output.result", "b": "B.output.result"},
            },
        ]
        orch, bus = _make_pipeline_orchestrator(tmp_path, stages, timeout=5)
        await bus.connect()

        goal = OrchestratorGoal(
            instruction="test",
            context={"x": "val_x", "y": "val_y"},
        )

        # Subscribe to intercept dispatched tasks and results.
        task_sub = await bus.subscribe("loom.tasks.incoming")
        result_sub = await bus.subscribe(f"loom.results.{goal.goal_id}")

        # Run the pipeline in a background task.
        pipeline_task = asyncio.create_task(orch.handle_message(goal.model_dump(mode="json")))

        # Collect the dispatched tasks — A and B should both arrive
        # before we send any results.
        dispatched = {}
        for _ in range(2):
            data = await asyncio.wait_for(task_sub.__anext__(), timeout=2)
            dispatched[data["metadata"]["stage_name"]] = data

        assert "A" in dispatched
        assert "B" in dispatched

        # Send results for A and B.
        for stage_name in ["A", "B"]:
            task_data = dispatched[stage_name]
            result = TaskResult(
                task_id=task_data["task_id"],
                worker_type=task_data["worker_type"],
                status=TaskStatus.COMPLETED,
                output={"result": f"{stage_name}_done"},
                processing_time_ms=10,
            )
            await bus.publish(
                f"loom.results.{goal.goal_id}",
                result.model_dump(mode="json"),
            )

        # Now stage C should be dispatched.
        c_data = await asyncio.wait_for(task_sub.__anext__(), timeout=2)
        assert c_data["metadata"]["stage_name"] == "C"

        # Send result for C.
        c_result = TaskResult(
            task_id=c_data["task_id"],
            worker_type=c_data["worker_type"],
            status=TaskStatus.COMPLETED,
            output={"result": "C_done"},
            processing_time_ms=10,
        )
        await bus.publish(
            f"loom.results.{goal.goal_id}",
            c_result.model_dump(mode="json"),
        )

        # Pipeline should complete.
        await asyncio.wait_for(pipeline_task, timeout=3)

        # Verify final result (skip intermediate stage results).
        final = await asyncio.wait_for(
            _wait_for_pipeline_result(result_sub, goal.goal_id),
            timeout=3,
        )
        assert final["status"] == TaskStatus.COMPLETED.value
        assert "A" in final["output"]
        assert "B" in final["output"]
        assert "C" in final["output"]

    @pytest.mark.asyncio
    async def test_stage_failure_aborts_pipeline(self, tmp_path):
        """If a parallel stage fails, the pipeline aborts with FAILED."""
        stages = [
            {
                "name": "A",
                "worker_type": "workerA",
                "tier": "local",
                "input_mapping": {"x": "goal.context.x"},
            },
            {
                "name": "B",
                "worker_type": "workerB",
                "tier": "local",
                "input_mapping": {"y": "goal.context.y"},
            },
        ]
        orch, bus = _make_pipeline_orchestrator(tmp_path, stages, timeout=5)
        await bus.connect()

        goal = OrchestratorGoal(
            instruction="test",
            context={"x": "1", "y": "2"},
        )

        task_sub = await bus.subscribe("loom.tasks.incoming")
        result_sub = await bus.subscribe(f"loom.results.{goal.goal_id}")

        pipeline_task = asyncio.create_task(orch.handle_message(goal.model_dump(mode="json")))

        # Both A and B dispatched concurrently.
        dispatched = {}
        for _ in range(2):
            data = await asyncio.wait_for(task_sub.__anext__(), timeout=2)
            dispatched[data["metadata"]["stage_name"]] = data

        # A succeeds, B fails.
        a_result = TaskResult(
            task_id=dispatched["A"]["task_id"],
            worker_type="workerA",
            status=TaskStatus.COMPLETED,
            output={"result": "ok"},
            processing_time_ms=10,
        )
        await bus.publish(
            f"loom.results.{goal.goal_id}",
            a_result.model_dump(mode="json"),
        )

        b_result = TaskResult(
            task_id=dispatched["B"]["task_id"],
            worker_type="workerB",
            status=TaskStatus.FAILED,
            error="something went wrong",
            processing_time_ms=10,
        )
        await bus.publish(
            f"loom.results.{goal.goal_id}",
            b_result.model_dump(mode="json"),
        )

        await asyncio.wait_for(pipeline_task, timeout=3)

        final = await asyncio.wait_for(
            _wait_for_pipeline_result(result_sub, goal.goal_id),
            timeout=3,
        )
        assert final["status"] == TaskStatus.FAILED.value
        assert "B" in final["error"]

    @pytest.mark.asyncio
    async def test_sequential_pipeline_unchanged(self, tmp_path):
        """A fully sequential pipeline still works correctly."""
        stages = [
            {
                "name": "first",
                "worker_type": "w1",
                "tier": "local",
                "input_mapping": {"x": "goal.context.x"},
            },
            {
                "name": "second",
                "worker_type": "w2",
                "tier": "local",
                "input_mapping": {"y": "first.output.result"},
            },
        ]
        orch, bus = _make_pipeline_orchestrator(tmp_path, stages, timeout=5)
        await bus.connect()

        goal = OrchestratorGoal(
            instruction="sequential test",
            context={"x": "input"},
        )

        task_sub = await bus.subscribe("loom.tasks.incoming")
        result_sub = await bus.subscribe(f"loom.results.{goal.goal_id}")

        pipeline_task = asyncio.create_task(orch.handle_message(goal.model_dump(mode="json")))

        # First stage dispatched.
        first_data = await asyncio.wait_for(task_sub.__anext__(), timeout=2)
        assert first_data["metadata"]["stage_name"] == "first"

        # Send result for first.
        first_result = TaskResult(
            task_id=first_data["task_id"],
            worker_type="w1",
            status=TaskStatus.COMPLETED,
            output={"result": "first_done"},
            processing_time_ms=10,
        )
        await bus.publish(
            f"loom.results.{goal.goal_id}",
            first_result.model_dump(mode="json"),
        )

        # Second stage dispatched.
        second_data = await asyncio.wait_for(task_sub.__anext__(), timeout=2)
        assert second_data["metadata"]["stage_name"] == "second"

        # Send result for second.
        second_result = TaskResult(
            task_id=second_data["task_id"],
            worker_type="w2",
            status=TaskStatus.COMPLETED,
            output={"result": "second_done"},
            processing_time_ms=10,
        )
        await bus.publish(
            f"loom.results.{goal.goal_id}",
            second_result.model_dump(mode="json"),
        )

        await asyncio.wait_for(pipeline_task, timeout=3)

        final = await asyncio.wait_for(
            _wait_for_pipeline_result(result_sub, goal.goal_id),
            timeout=3,
        )
        assert final["status"] == TaskStatus.COMPLETED.value
        assert final["output"]["first"]["result"] == "first_done"
        assert final["output"]["second"]["result"] == "second_done"


# --- max_concurrent_goals tests ---


class TestPipelineConcurrentGoals:
    def test_default_max_concurrent_goals_is_one(self, tmp_path):
        """Without config, max_concurrent_goals defaults to 1."""
        orch, _ = _make_pipeline_orchestrator(tmp_path, stages=[])
        assert orch.max_concurrent == 1

    def test_max_concurrent_goals_from_config(self, tmp_path):
        """Config value is passed through to BaseActor.max_concurrent."""
        orch, _ = _make_pipeline_orchestrator(
            tmp_path,
            stages=[],
            max_concurrent_goals=3,
        )
        assert orch.max_concurrent == 3

    def test_bus_injection_via_constructor(self, tmp_path):
        """The bus= keyword argument is forwarded to BaseActor."""
        orch, bus = _make_pipeline_orchestrator(tmp_path, stages=[])
        assert orch._bus is bus
