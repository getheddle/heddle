"""Test PipelineOrchestrator (unit tests, no infrastructure)."""
import pytest

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
            "intro", "body", "conclusion"
        ]

    def test_boolean_value(self):
        ctx = {"extract": {"output": {"has_tables": True}}}
        assert PipelineOrchestrator._resolve_path("extract.output.has_tables", ctx) is True


# --- _evaluate_condition tests ---

class TestEvaluateCondition:
    def test_equals_true(self):
        ctx = {"extract": {"output": {"has_tables": True}}}
        assert PipelineOrchestrator._evaluate_condition(
            "extract.output.has_tables == true", ctx
        ) is True

    def test_equals_false(self):
        ctx = {"extract": {"output": {"has_tables": False}}}
        assert PipelineOrchestrator._evaluate_condition(
            "extract.output.has_tables == true", ctx
        ) is False

    def test_not_equals_none(self):
        ctx = {"extract": {"output": {"data": "something"}}}
        assert PipelineOrchestrator._evaluate_condition(
            "extract.output.data != null", ctx
        ) is True

    def test_equals_none(self):
        ctx = {"extract": {"output": {"data": None}}}
        assert PipelineOrchestrator._evaluate_condition(
            "extract.output.data == null", ctx
        ) is True

    def test_missing_path_returns_false(self):
        ctx = {"extract": {"output": {}}}
        assert PipelineOrchestrator._evaluate_condition(
            "extract.output.nonexistent == true", ctx
        ) is False

    def test_invalid_condition_defaults_true(self):
        ctx = {}
        assert PipelineOrchestrator._evaluate_condition("invalid", ctx) is True

    def test_string_comparison(self):
        ctx = {"classify": {"output": {"document_type": "invoice"}}}
        assert PipelineOrchestrator._evaluate_condition(
            "classify.output.document_type == invoice", ctx
        ) is True


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
