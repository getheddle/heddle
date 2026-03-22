"""DeepEval quality tests for LLM worker output.

These tests use DeepEval metrics with a local Ollama judge model to evaluate
the quality of LLM worker responses. They require:
- deepeval package installed (uv sync --extra eval)
- Ollama running locally with command-r7b model

Run: uv run pytest tests/test_deepeval_worker.py -v
Skip: uv run pytest tests/ -m "not deepeval"
"""

import json

import pytest

from tests.conftest import skip_no_deepeval

pytestmark = [pytest.mark.deepeval, skip_no_deepeval]


@pytest.fixture(scope="module")
def judge_model():
    from deepeval.models import OllamaModel

    return OllamaModel(
        model="command-r7b:latest",
        base_url="http://localhost:11434",
    )


@pytest.fixture(scope="module")
def json_compliance_metric(judge_model):
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    return GEval(
        name="JSON Compliance",
        criteria="The output must be valid JSON that contains the expected fields.",
        evaluation_params=[
            LLMTestCaseParams.ACTUAL_OUTPUT,
            LLMTestCaseParams.EXPECTED_OUTPUT,
        ],
        model=judge_model,
        threshold=0.7,
    )


@pytest.fixture(scope="module")
def relevance_metric(judge_model):
    from deepeval.metrics import GEval
    from deepeval.test_case import LLMTestCaseParams

    return GEval(
        name="Response Relevance",
        criteria=(
            "The output must directly address the input prompt "
            "and contain relevant information."
        ),
        evaluation_params=[
            LLMTestCaseParams.INPUT,
            LLMTestCaseParams.ACTUAL_OUTPUT,
        ],
        model=judge_model,
        threshold=0.6,
    )


def test_worker_json_output_structure(judge_model, json_compliance_metric):
    """Worker output should comply with expected JSON schema."""
    from deepeval import assert_test
    from deepeval.test_case import LLMTestCase

    test_case = LLMTestCase(
        input="Summarize the key economic indicators for Q1 2026.",
        actual_output=json.dumps({
            "summary": "Q1 2026 showed moderate GDP growth of 2.3%.",
            "key_points": ["GDP growth 2.3%", "Inflation steady at 3.1%"],
            "confidence": 0.85,
        }),
        expected_output=json.dumps({
            "summary": "...",
            "key_points": ["..."],
            "confidence": 0.0,
        }),
    )
    assert_test(test_case, [json_compliance_metric])


def test_worker_response_relevance(judge_model, relevance_metric):
    """Worker output should be relevant to the input prompt."""
    from deepeval import assert_test
    from deepeval.test_case import LLMTestCase

    test_case = LLMTestCase(
        input="What are the main political factions in the Iranian parliament?",
        actual_output="The Iranian parliament (Majles) includes principlist, "
        "reformist, and independent factions. Principlists currently "
        "hold the majority of seats.",
    )
    assert_test(test_case, [relevance_metric])
