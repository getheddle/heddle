"""
Result aggregation for orchestrators.

Responsible for combining results from multiple workers
into a coherent final output.

This module is used by OrchestratorActor (runner.py), NOT by
PipelineOrchestrator (which simply collects stage outputs into a dict).

TODO: Implement result synthesis logic. Expected API:

    class ResultSynthesizer:
        def __init__(self, backend: LLMBackend):
            ...

        async def synthesize(
            self,
            goal: OrchestratorGoal,
            results: list[TaskResult],
        ) -> dict[str, Any]:
            '''
            Ask the LLM to combine worker results into a final answer.

            The LLM receives:
            - The original goal
            - All worker results (outputs, errors, metadata)
            - Instructions to produce a coherent synthesis

            Returns a dict conforming to the orchestrator's output contract.
            '''
            ...

    Implementation notes:
    - Handle partial failures: some workers may have failed while others succeeded
    - The synthesizer should flag conflicts between worker outputs
    - Consider token limits: if combined results are too large, summarize each first
    - Output format should be consistent regardless of which workers were invoked
"""
from __future__ import annotations
