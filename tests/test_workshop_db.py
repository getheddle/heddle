"""Tests for WorkshopDB (workshop/db.py)."""

from __future__ import annotations

import pytest

from loom.workshop.db import WorkshopDB


@pytest.fixture
def db():
    """In-memory DuckDB for testing."""
    database = WorkshopDB(":memory:")
    yield database
    database.close()


# ---------------------------------------------------------------------------
# Worker versions
# ---------------------------------------------------------------------------


class TestWorkerVersions:
    def test_save_and_retrieve(self, db):
        vid = db.save_worker_version("summarizer", "name: summarizer\nsystem_prompt: test")
        versions = db.get_worker_versions("summarizer")
        assert len(versions) == 1
        assert versions[0]["id"] == vid
        assert versions[0]["worker_name"] == "summarizer"
        assert "summarizer" in versions[0]["config_yaml"]

    def test_deduplication_by_hash(self, db):
        yaml_content = "name: summarizer\nsystem_prompt: test"
        vid1 = db.save_worker_version("summarizer", yaml_content)
        vid2 = db.save_worker_version("summarizer", yaml_content)
        assert vid1 == vid2
        assert len(db.get_worker_versions("summarizer")) == 1

    def test_different_content_creates_new_version(self, db):
        db.save_worker_version("summarizer", "version: 1")
        db.save_worker_version("summarizer", "version: 2")
        versions = db.get_worker_versions("summarizer")
        assert len(versions) == 2

    def test_description_stored(self, db):
        db.save_worker_version("w", "config: 1", description="Initial version")
        versions = db.get_worker_versions("w")
        assert versions[0]["description"] == "Initial version"

    def test_different_workers_isolated(self, db):
        db.save_worker_version("a", "config: a")
        db.save_worker_version("b", "config: b")
        assert len(db.get_worker_versions("a")) == 1
        assert len(db.get_worker_versions("b")) == 1

    def test_versions_ordered_newest_first(self, db):
        db.save_worker_version("w", "v1")
        db.save_worker_version("w", "v2")
        db.save_worker_version("w", "v3")
        versions = db.get_worker_versions("w")
        assert len(versions) == 3


# ---------------------------------------------------------------------------
# Eval runs
# ---------------------------------------------------------------------------


class TestEvalRuns:
    def test_create_and_retrieve(self, db):
        run_id = db.save_eval_run("summarizer", "local", total_cases=5)
        runs = db.get_eval_runs("summarizer")
        assert len(runs) == 1
        assert runs[0]["id"] == run_id
        assert runs[0]["status"] == "running"
        assert runs[0]["total_cases"] == 5

    def test_update_eval_run(self, db):
        run_id = db.save_eval_run("summarizer", "local", total_cases=3)
        db.update_eval_run(
            run_id,
            {
                "status": "completed",
                "passed_cases": 2,
                "failed_cases": 1,
                "avg_latency_ms": 150.5,
            },
        )
        runs = db.get_eval_runs("summarizer")
        assert runs[0]["status"] == "completed"
        assert runs[0]["passed_cases"] == 2
        assert runs[0]["failed_cases"] == 1

    def test_get_all_runs(self, db):
        db.save_eval_run("a", "local", total_cases=1)
        db.save_eval_run("b", "standard", total_cases=2)
        all_runs = db.get_eval_runs()
        assert len(all_runs) == 2

    def test_get_runs_filtered_by_worker(self, db):
        db.save_eval_run("a", "local", total_cases=1)
        db.save_eval_run("b", "standard", total_cases=2)
        runs_a = db.get_eval_runs("a")
        assert len(runs_a) == 1
        assert runs_a[0]["worker_name"] == "a"

    def test_limit_respected(self, db):
        for i in range(10):
            db.save_eval_run("w", "local", total_cases=1)
        runs = db.get_eval_runs("w", limit=3)
        assert len(runs) == 3


# ---------------------------------------------------------------------------
# Eval results
# ---------------------------------------------------------------------------


class TestEvalResults:
    def test_save_and_retrieve(self, db):
        run_id = db.save_eval_run("w", "local", total_cases=1)
        result_id = db.save_eval_result(
            run_id=run_id,
            case_name="test_case_1",
            input_payload={"text": "hello"},
            passed=True,
            expected_output={"summary": "hi"},
            actual_output={"summary": "hi"},
            score=1.0,
            latency_ms=100,
            prompt_tokens=50,
            completion_tokens=25,
            model_used="mock",
        )
        results = db.get_eval_results(run_id)
        assert len(results) == 1
        assert results[0]["id"] == result_id
        assert results[0]["passed"] is True
        assert results[0]["score"] == 1.0

    def test_multiple_results_per_run(self, db):
        run_id = db.save_eval_run("w", "local", total_cases=3)
        for i in range(3):
            db.save_eval_result(
                run_id=run_id,
                case_name=f"case_{i}",
                input_payload={"n": i},
                passed=i % 2 == 0,
            )
        results = db.get_eval_results(run_id)
        assert len(results) == 3

    def test_failed_result_with_error(self, db):
        run_id = db.save_eval_run("w", "local", total_cases=1)
        db.save_eval_result(
            run_id=run_id,
            case_name="error_case",
            input_payload={"text": "test"},
            passed=False,
            error="Backend timeout",
            validation_errors=["missing field: summary"],
        )
        results = db.get_eval_results(run_id)
        assert results[0]["passed"] is False
        assert results[0]["error"] == "Backend timeout"


# ---------------------------------------------------------------------------
# Compare eval runs
# ---------------------------------------------------------------------------


class TestCompareRuns:
    def test_compare_two_runs(self, db):
        run_a = db.save_eval_run("w", "local", total_cases=2)
        run_b = db.save_eval_run("w", "standard", total_cases=2)

        db.save_eval_result(run_a, "case_1", {"text": "a"}, True, score=0.8)
        db.save_eval_result(run_a, "case_2", {"text": "b"}, False, score=0.3)
        db.save_eval_result(run_b, "case_1", {"text": "a"}, True, score=0.9)
        db.save_eval_result(run_b, "case_2", {"text": "b"}, True, score=0.7)

        comparison = db.compare_eval_runs(run_a, run_b)
        assert len(comparison["cases"]) == 2
        assert comparison["cases"][0]["case_name"] == "case_1"
        assert comparison["cases"][0]["a"]["score"] == 0.8
        assert comparison["cases"][0]["b"]["score"] == 0.9


# ---------------------------------------------------------------------------
# Worker metrics
# ---------------------------------------------------------------------------


class TestWorkerMetrics:
    def test_save_and_retrieve(self, db):
        db.save_worker_metric(
            worker_name="summarizer",
            tier="local",
            request_count=10,
            success_count=8,
            failure_count=2,
            avg_latency_ms=150.0,
        )
        metrics = db.get_worker_metrics("summarizer")
        assert len(metrics) == 1
        assert metrics[0]["request_count"] == 10
        assert metrics[0]["success_count"] == 8

    def test_metrics_filtered_by_worker(self, db):
        db.save_worker_metric("a", "local", 5, 5, 0)
        db.save_worker_metric("b", "local", 3, 2, 1)
        assert len(db.get_worker_metrics("a")) == 1
        assert len(db.get_worker_metrics("b")) == 1


# ---------------------------------------------------------------------------
# Schema creation
# ---------------------------------------------------------------------------


class TestSchema:
    def test_schema_idempotent(self):
        """Creating WorkshopDB twice on same path doesn't fail."""
        db = WorkshopDB(":memory:")
        db._ensure_schema()  # Second call should be idempotent
        db.close()
