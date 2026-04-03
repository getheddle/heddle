"""Tests for heddle.workshop.config_impact module."""

from __future__ import annotations

from unittest.mock import MagicMock

from heddle.workshop.config_impact import _find_downstream, _infer_dependencies, get_impact


class TestInferDependencies:
    def test_goal_only_references(self):
        stages = [
            {"name": "a", "input_mapping": {"x": "goal.context.x"}},
            {"name": "b", "input_mapping": {"y": "goal.context.y"}},
        ]
        deps = _infer_dependencies(stages)
        assert deps == {"a": set(), "b": set()}

    def test_inter_stage_dependency(self):
        stages = [
            {"name": "extract", "input_mapping": {"x": "goal.context.x"}},
            {"name": "summarize", "input_mapping": {"text": "extract.output.text"}},
        ]
        deps = _infer_dependencies(stages)
        assert deps["extract"] == set()
        assert deps["summarize"] == {"extract"}

    def test_explicit_depends_on(self):
        stages = [
            {"name": "a", "input_mapping": {"x": "goal.context.x"}},
            {"name": "b", "depends_on": ["a"], "input_mapping": {"y": "goal.context.y"}},
        ]
        deps = _infer_dependencies(stages)
        assert deps["b"] == {"a"}

    def test_unknown_depends_on_filtered(self):
        stages = [
            {"name": "a"},
            {"name": "b", "depends_on": ["a", "nonexistent"]},
        ]
        deps = _infer_dependencies(stages)
        assert deps["b"] == {"a"}


class TestFindDownstream:
    def test_direct_downstream(self):
        deps = {"a": set(), "b": {"a"}, "c": {"b"}}
        downstream = _find_downstream({"a"}, deps)
        assert downstream == {"b", "c"}

    def test_no_downstream(self):
        deps = {"a": set(), "b": set()}
        downstream = _find_downstream({"a"}, deps)
        assert downstream == set()

    def test_multiple_sources(self):
        deps = {"a": set(), "b": set(), "c": {"a"}, "d": {"b"}}
        downstream = _find_downstream({"a", "b"}, deps)
        assert downstream == {"c", "d"}

    def test_diamond_dependency(self):
        deps = {"a": set(), "b": {"a"}, "c": {"a"}, "d": {"b", "c"}}
        downstream = _find_downstream({"a"}, deps)
        assert downstream == {"b", "c", "d"}


class TestGetImpact:
    def _make_config_manager(self, pipelines=None, workers=None):
        mgr = MagicMock()
        mgr.list_pipelines.return_value = pipelines or []
        mgr.get_pipeline.side_effect = lambda name: {p["name"]: p for p in (pipelines or [])}.get(
            name, {}
        )
        if workers:
            mgr.get_worker.side_effect = lambda name: workers.get(name, {})
        else:
            mgr.get_worker.side_effect = FileNotFoundError("not found")
        return mgr

    def test_no_pipelines(self):
        mgr = self._make_config_manager()
        result = get_impact("summarizer", mgr)
        assert result["total_pipelines"] == 0
        assert result["total_stages"] == 0
        assert result["risk"] == "low"

    def test_worker_in_one_pipeline(self):
        pipeline = {
            "name": "doc_pipeline",
            "pipeline_stages": [
                {
                    "name": "extract",
                    "worker_type": "extractor",
                    "input_mapping": {"x": "goal.context.x"},
                },
                {
                    "name": "summarize",
                    "worker_type": "summarizer",
                    "input_mapping": {"text": "extract.output.text"},
                },
            ],
        }
        mgr = self._make_config_manager(
            pipelines=[pipeline],
            workers={"summarizer": {"output_schema": {"type": "object"}}},
        )
        result = get_impact("summarizer", mgr)
        assert result["total_pipelines"] == 1
        assert result["total_stages"] == 1
        assert result["pipelines"][0]["name"] == "doc_pipeline"
        assert result["pipelines"][0]["stages"][0]["name"] == "summarize"
        assert result["has_output_schema"] is True

    def test_worker_with_downstream(self):
        pipeline = {
            "name": "pipeline",
            "pipeline_stages": [
                {
                    "name": "extract",
                    "worker_type": "extractor",
                    "input_mapping": {"x": "goal.context.x"},
                },
                {
                    "name": "classify",
                    "worker_type": "classifier",
                    "input_mapping": {"text": "extract.output.text"},
                },
                {
                    "name": "report",
                    "worker_type": "reporter",
                    "input_mapping": {"cat": "classify.output.category"},
                },
            ],
        }
        mgr = self._make_config_manager(pipelines=[pipeline])
        result = get_impact("extractor", mgr)
        assert result["total_pipelines"] == 1
        assert result["total_stages"] == 1
        # classify and report are downstream of extract
        assert set(result["pipelines"][0]["downstream"]) == {"classify", "report"}
        assert result["total_downstream"] == 2
        assert result["risk"] == "high"

    def test_worker_not_in_any_pipeline(self):
        pipeline = {
            "name": "p",
            "pipeline_stages": [
                {"name": "a", "worker_type": "other"},
            ],
        }
        mgr = self._make_config_manager(pipelines=[pipeline])
        result = get_impact("summarizer", mgr)
        assert result["total_pipelines"] == 0
        assert result["risk"] == "low"

    def test_worker_no_output_schema(self):
        mgr = self._make_config_manager(workers={"summarizer": {}})
        result = get_impact("summarizer", mgr)
        assert result["has_output_schema"] is False

    def test_multiple_pipelines(self):
        p1 = {
            "name": "p1",
            "pipeline_stages": [
                {
                    "name": "s1",
                    "worker_type": "summarizer",
                    "input_mapping": {"x": "goal.context.x"},
                },
            ],
        }
        p2 = {
            "name": "p2",
            "pipeline_stages": [
                {
                    "name": "s2",
                    "worker_type": "summarizer",
                    "input_mapping": {"x": "goal.context.x"},
                },
                {"name": "s3", "worker_type": "other", "input_mapping": {"y": "s2.output.y"}},
            ],
        }
        mgr = self._make_config_manager(pipelines=[p1, p2])
        result = get_impact("summarizer", mgr)
        assert result["total_pipelines"] == 2
        assert result["total_stages"] == 2
        # s3 is downstream of s2 (summarizer stage) in p2
        assert result["total_downstream"] == 1

    def test_pipeline_load_failure_skipped(self):
        mgr = MagicMock()
        mgr.list_pipelines.return_value = [{"name": "broken"}]
        mgr.get_pipeline.side_effect = Exception("bad config")
        mgr.get_worker.side_effect = FileNotFoundError
        result = get_impact("summarizer", mgr)
        assert result["total_pipelines"] == 0


class TestGetImpactViaApp:
    """Test the /workers/{name}/impact endpoint via Workshop app."""

    def test_impact_endpoint(self, tmp_path):
        from fastapi.testclient import TestClient

        from heddle.workshop.app import create_app

        configs_dir = tmp_path / "configs"
        workers_dir = configs_dir / "workers"
        workers_dir.mkdir(parents=True)
        orch_dir = configs_dir / "orchestrators"
        orch_dir.mkdir()

        worker_yaml = workers_dir / "summarizer.yaml"
        worker_yaml.write_text(
            "name: summarizer\n"
            "system_prompt: Summarize.\n"
            "input_schema:\n"
            "  type: object\n"
            "  required: [text]\n"
            "  properties:\n"
            "    text: {type: string}\n"
            "output_schema:\n"
            "  type: object\n"
            "  required: [summary]\n"
            "  properties:\n"
            "    summary: {type: string}\n"
            "default_model_tier: local\n"
        )

        app = create_app(
            configs_dir=str(configs_dir),
            db_path=":memory:",
            apps_dir=str(tmp_path / "apps"),
        )
        client = TestClient(app)

        resp = client.get("/workers/summarizer/impact")
        assert resp.status_code == 200
        data = resp.json()
        assert data["worker_name"] == "summarizer"
        assert data["has_output_schema"] is True
        assert data["total_pipelines"] == 0

    def test_impact_panel_endpoint(self, tmp_path):
        from fastapi.testclient import TestClient

        from heddle.workshop.app import create_app

        configs_dir = tmp_path / "configs"
        workers_dir = configs_dir / "workers"
        workers_dir.mkdir(parents=True)
        orch_dir = configs_dir / "orchestrators"
        orch_dir.mkdir()

        worker_yaml = workers_dir / "summarizer.yaml"
        worker_yaml.write_text(
            "name: summarizer\n"
            "system_prompt: Summarize.\n"
            "input_schema:\n"
            "  type: object\n"
            "  required: [text]\n"
            "  properties:\n"
            "    text: {type: string}\n"
            "output_schema:\n"
            "  type: object\n"
            "  required: [summary]\n"
            "  properties:\n"
            "    summary: {type: string}\n"
            "default_model_tier: local\n"
        )

        app = create_app(
            configs_dir=str(configs_dir),
            db_path=":memory:",
            apps_dir=str(tmp_path / "apps"),
        )
        client = TestClient(app)

        resp = client.get("/workers/summarizer/impact-panel")
        assert resp.status_code == 200
        assert "not used in any pipeline" in resp.text

    def test_impact_panel_with_pipeline(self, tmp_path):
        from fastapi.testclient import TestClient

        from heddle.workshop.app import create_app

        configs_dir = tmp_path / "configs"
        workers_dir = configs_dir / "workers"
        workers_dir.mkdir(parents=True)
        orch_dir = configs_dir / "orchestrators"
        orch_dir.mkdir()

        worker_yaml = workers_dir / "extractor.yaml"
        worker_yaml.write_text(
            "name: extractor\n"
            "system_prompt: Extract.\n"
            "input_schema:\n"
            "  type: object\n"
            "  required: [text]\n"
            "  properties:\n"
            "    text: {type: string}\n"
            "output_schema:\n"
            "  type: object\n"
            "  required: [data]\n"
            "  properties:\n"
            "    data: {type: string}\n"
            "default_model_tier: local\n"
        )

        workers_dir.joinpath("summarizer.yaml").write_text(
            "name: summarizer\n"
            "system_prompt: Summarize.\n"
            "input_schema:\n"
            "  type: object\n"
            "  required: [text]\n"
            "  properties:\n"
            "    text: {type: string}\n"
            "default_model_tier: local\n"
        )

        orch_dir.joinpath("doc_pipeline.yaml").write_text(
            "name: doc_pipeline\n"
            "pipeline_stages:\n"
            "  - name: extract\n"
            "    worker_type: extractor\n"
            "    tier: local\n"
            "    input_mapping:\n"
            "      text: goal.context.text\n"
            "  - name: summarize\n"
            "    worker_type: summarizer\n"
            "    tier: local\n"
            "    input_mapping:\n"
            "      text: extract.output.data\n"
        )

        app = create_app(
            configs_dir=str(configs_dir),
            db_path=":memory:",
            apps_dir=str(tmp_path / "apps"),
        )
        client = TestClient(app)

        resp = client.get("/workers/extractor/impact-panel")
        assert resp.status_code == 200
        assert "doc_pipeline" in resp.text
        assert "summarize" in resp.text
        assert "downstream" in resp.text.lower()
        assert "HIGH RISK" in resp.text
