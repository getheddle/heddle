"""
EvalRunner — systematic test suite execution with scoring.

Runs a list of test cases against a worker config, scores each result,
and persists everything to WorkshopDB.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import structlog

if TYPE_CHECKING:
    from loom.workshop.db import WorkshopDB
    from loom.workshop.test_runner import WorkerTestRunner

logger = structlog.get_logger()


def _score_exact_match(expected: dict, actual: dict) -> tuple[float, dict]:
    """Score 1.0 if outputs are identical, 0.0 otherwise."""
    match = expected == actual
    return (1.0 if match else 0.0, {"method": "exact_match", "match": match})


def _score_field_match(expected: dict, actual: dict) -> tuple[float, dict]:
    """Score = fraction of expected fields that match in actual output."""
    if not expected:
        return (1.0, {"method": "field_match", "fields": {}})

    field_scores = {}
    for key, expected_val in expected.items():
        actual_val = actual.get(key)
        if actual_val == expected_val:
            field_scores[key] = 1.0
        elif isinstance(expected_val, str) and isinstance(actual_val, str):
            # Normalized string comparison (case-insensitive, strip whitespace)
            field_scores[key] = (
                1.0 if expected_val.strip().lower() == actual_val.strip().lower() else 0.0
            )
        elif isinstance(expected_val, list) and isinstance(actual_val, list):
            # Check if expected items are a subset of actual
            expected_set = {str(v) for v in expected_val}
            actual_set = {str(v) for v in actual_val}
            if expected_set:
                overlap = len(expected_set & actual_set) / len(expected_set)
                field_scores[key] = overlap
            else:
                field_scores[key] = 1.0
        else:
            field_scores[key] = 0.0

    avg_score = sum(field_scores.values()) / len(field_scores)
    return (avg_score, {"method": "field_match", "fields": field_scores})


class EvalRunner:
    """Run a test suite against a worker config and store results.

    Args:
        test_runner: WorkerTestRunner instance for executing individual tests.
        db: WorkshopDB for persisting results.
    """

    def __init__(self, test_runner: WorkerTestRunner, db: WorkshopDB) -> None:
        self.test_runner = test_runner
        self.db = db

    async def run_suite(
        self,
        config: dict[str, Any],
        test_suite: list[dict[str, Any]],
        tier: str | None = None,
        scoring: str = "field_match",
        max_concurrency: int = 3,
    ) -> str:
        """Run all test cases and store results.

        Args:
            config: Worker config dict.
            test_suite: List of ``{"name": str, "input": dict, "expected_output": dict}``.
            tier: Model tier override.
            scoring: Scoring method — ``"exact_match"`` or ``"field_match"``.
            max_concurrency: Max concurrent test case executions.

        Returns:
            The eval run ID.
        """
        import yaml

        worker_name = config.get("name", "unknown")

        # Save worker version
        config_yaml = yaml.dump(config, default_flow_style=False, sort_keys=False)
        version_id = self.db.save_worker_version(worker_name, config_yaml)

        resolved_tier = tier or config.get("default_model_tier", "standard")

        # Create eval run
        run_id = self.db.save_eval_run(
            worker_name=worker_name,
            tier=resolved_tier,
            total_cases=len(test_suite),
            worker_version_id=version_id,
        )

        logger.info(
            "eval.suite_started",
            run_id=run_id,
            worker=worker_name,
            cases=len(test_suite),
            scoring=scoring,
        )

        # Select scoring function
        score_fn = _score_field_match if scoring == "field_match" else _score_exact_match

        # Run test cases with bounded concurrency
        semaphore = asyncio.Semaphore(max_concurrency)
        passed = 0
        failed = 0
        total_latency = 0
        total_prompt = 0
        total_completion = 0

        async def run_one(case: dict) -> None:
            nonlocal passed, failed, total_latency, total_prompt, total_completion
            async with semaphore:
                case_name = case.get("name", "unnamed")
                input_payload = case.get("input", {})
                expected = case.get("expected_output")

                result = await self.test_runner.run(config, input_payload, tier=resolved_tier)

                # Score
                score = 0.0
                score_details = {}
                case_passed = result.success

                if result.output and expected:
                    score, score_details = score_fn(expected, result.output)
                    case_passed = case_passed and score >= 0.5
                elif result.output and not expected:
                    score = 1.0 if result.success else 0.0
                    score_details = {"method": scoring, "note": "no expected output"}

                if case_passed:
                    passed += 1
                else:
                    failed += 1

                total_latency += result.latency_ms
                total_prompt += result.token_usage.get("prompt_tokens", 0)
                total_completion += result.token_usage.get("completion_tokens", 0)

                self.db.save_eval_result(
                    run_id=run_id,
                    case_name=case_name,
                    input_payload=input_payload,
                    passed=case_passed,
                    expected_output=expected,
                    actual_output=result.output,
                    raw_response=result.raw_response,
                    validation_errors=result.validation_errors or None,
                    score=score,
                    score_details=score_details,
                    latency_ms=result.latency_ms,
                    prompt_tokens=result.token_usage.get("prompt_tokens"),
                    completion_tokens=result.token_usage.get("completion_tokens"),
                    model_used=result.model_used,
                    error=result.error,
                )

        await asyncio.gather(*(run_one(case) for case in test_suite))

        # Update run summary
        n = len(test_suite)
        self.db.update_eval_run(
            run_id,
            {
                "status": "completed",
                "completed_at": datetime.now(UTC),
                "passed_cases": passed,
                "failed_cases": failed,
                "avg_latency_ms": total_latency / n if n else 0,
                "avg_prompt_tokens": total_prompt / n if n else 0,
                "avg_completion_tokens": total_completion / n if n else 0,
            },
        )

        logger.info(
            "eval.suite_completed",
            run_id=run_id,
            passed=passed,
            failed=failed,
            total=n,
        )

        return run_id
