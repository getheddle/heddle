"""Tests for EvalRunner (workshop/eval_runner.py)."""

from __future__ import annotations

import json

import pytest

from loom.worker.backends import LLMBackend
from loom.workshop.db import WorkshopDB
from loom.workshop.eval_runner import EvalRunner, _score_exact_match, _score_field_match
from loom.workshop.test_runner import WorkerTestRunner

# ---------------------------------------------------------------------------
# Mock backend
# ---------------------------------------------------------------------------


class MockEvalBackend(LLMBackend):
    """Returns output based on input payload content."""

    async def complete(
        self, system_prompt, user_message, max_tokens=2000, temperature=0.0, **kwargs
    ):
        # Parse the input to generate predictable output
        try:
            payload = json.loads(user_message)
            text = payload.get("text", "")
        except json.JSONDecodeError:
            text = ""
        return {
            "content": json.dumps({"summary": f"Summary of: {text}"}),
            "model": "mock-eval",
            "prompt_tokens": 50,
            "completion_tokens": 25,
            "tool_calls": None,
            "stop_reason": "end_turn",
        }


EVAL_CONFIG = {
    "name": "eval_worker",
    "system_prompt": "Summarize the text.",
    "input_schema": {
        "type": "object",
        "required": ["text"],
        "properties": {"text": {"type": "string"}},
    },
    "output_schema": {
        "type": "object",
        "required": ["summary"],
        "properties": {"summary": {"type": "string"}},
    },
    "default_model_tier": "local",
}


# ---------------------------------------------------------------------------
# Scoring function tests
# ---------------------------------------------------------------------------


class TestScoringFunctions:
    def test_exact_match_identical(self):
        score, details = _score_exact_match({"a": 1}, {"a": 1})
        assert score == 1.0

    def test_exact_match_different(self):
        score, details = _score_exact_match({"a": 1}, {"a": 2})
        assert score == 0.0

    def test_field_match_all_match(self):
        score, details = _score_field_match(
            {"name": "Alice", "age": 30},
            {"name": "Alice", "age": 30},
        )
        assert score == 1.0

    def test_field_match_partial(self):
        score, details = _score_field_match(
            {"name": "Alice", "age": 30},
            {"name": "Alice", "age": 25},
        )
        assert score == 0.5
        assert details["fields"]["name"] == 1.0
        assert details["fields"]["age"] == 0.0

    def test_field_match_case_insensitive_strings(self):
        score, _ = _score_field_match(
            {"name": "Alice"},
            {"name": "alice"},
        )
        assert score == 1.0

    def test_field_match_list_subset(self):
        score, details = _score_field_match(
            {"tags": ["a", "b"]},
            {"tags": ["a", "b", "c"]},
        )
        assert score == 1.0  # All expected items present

    def test_field_match_list_partial(self):
        score, details = _score_field_match(
            {"tags": ["a", "b"]},
            {"tags": ["a", "c"]},
        )
        assert score == 0.5  # Only "a" matches

    def test_field_match_empty_expected(self):
        score, _ = _score_field_match({}, {"any": "thing"})
        assert score == 1.0

    def test_field_match_missing_field(self):
        score, details = _score_field_match(
            {"name": "Alice"},
            {},
        )
        assert score == 0.0


# ---------------------------------------------------------------------------
# EvalRunner tests
# ---------------------------------------------------------------------------


class TestEvalRunner:
    @pytest.fixture
    def runner_and_db(self):
        db = WorkshopDB(":memory:")
        backend = MockEvalBackend()
        test_runner = WorkerTestRunner({"local": backend})
        eval_runner = EvalRunner(test_runner, db)
        yield eval_runner, db
        db.close()

    @pytest.mark.asyncio
    async def test_run_suite_basic(self, runner_and_db):
        eval_runner, db = runner_and_db

        suite = [
            {
                "name": "case_1",
                "input": {"text": "hello"},
                "expected_output": {"summary": "Summary of: hello"},
            },
            {
                "name": "case_2",
                "input": {"text": "world"},
                "expected_output": {"summary": "Summary of: world"},
            },
        ]

        run_id = await eval_runner.run_suite(EVAL_CONFIG, suite)

        runs = db.get_eval_runs("eval_worker")
        assert len(runs) == 1
        assert runs[0]["status"] == "completed"
        assert runs[0]["total_cases"] == 2

        results = db.get_eval_results(run_id)
        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_run_suite_records_scores(self, runner_and_db):
        eval_runner, db = runner_and_db

        suite = [
            {
                "name": "match",
                "input": {"text": "test"},
                "expected_output": {"summary": "Summary of: test"},
            },
            {
                "name": "mismatch",
                "input": {"text": "test"},
                "expected_output": {"summary": "wrong"},
            },
        ]

        run_id = await eval_runner.run_suite(EVAL_CONFIG, suite, scoring="field_match")
        results = db.get_eval_results(run_id)

        by_name = {r["case_name"]: r for r in results}
        assert by_name["match"]["score"] == 1.0
        assert by_name["mismatch"]["score"] < 1.0

    @pytest.mark.asyncio
    async def test_run_suite_saves_worker_version(self, runner_and_db):
        eval_runner, db = runner_and_db

        suite = [{"name": "c1", "input": {"text": "x"}}]
        await eval_runner.run_suite(EVAL_CONFIG, suite)

        versions = db.get_worker_versions("eval_worker")
        assert len(versions) == 1

    @pytest.mark.asyncio
    async def test_run_suite_without_expected_output(self, runner_and_db):
        eval_runner, db = runner_and_db

        suite = [
            {"name": "no_expected", "input": {"text": "test"}},
        ]
        run_id = await eval_runner.run_suite(EVAL_CONFIG, suite)

        results = db.get_eval_results(run_id)
        assert len(results) == 1
        # Should still pass since output is valid
        assert results[0]["passed"] is True

    @pytest.mark.asyncio
    async def test_run_suite_exact_match_scoring(self, runner_and_db):
        eval_runner, db = runner_and_db

        suite = [
            {
                "name": "exact",
                "input": {"text": "test"},
                "expected_output": {"summary": "Summary of: test"},
            },
        ]
        run_id = await eval_runner.run_suite(EVAL_CONFIG, suite, scoring="exact_match")

        results = db.get_eval_results(run_id)
        assert results[0]["score"] == 1.0

    @pytest.mark.asyncio
    async def test_run_summary_aggregates(self, runner_and_db):
        eval_runner, db = runner_and_db

        suite = [{"name": f"case_{i}", "input": {"text": f"text_{i}"}} for i in range(5)]
        await eval_runner.run_suite(EVAL_CONFIG, suite)

        runs = db.get_eval_runs("eval_worker")
        run = runs[0]
        assert run["total_cases"] == 5
        assert run["passed_cases"] + run["failed_cases"] == 5
        assert run["avg_latency_ms"] is not None
