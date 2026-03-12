"""
Task decomposition logic for orchestrators.

Responsible for breaking down complex goals into concrete subtasks
that can be routed to individual workers.

This module is used by OrchestratorActor (runner.py), NOT by
PipelineOrchestrator (which has its stages pre-defined in YAML).

TODO: Implement LLM-based decomposition. Expected API:

    class TaskDecomposer:
        def __init__(self, backend: LLMBackend, available_workers: list[str]):
            ...

        async def decompose(self, goal: OrchestratorGoal) -> list[TaskMessage]:
            '''
            Ask the LLM to break the goal into subtasks.

            The LLM receives:
            - The goal instruction and context
            - A list of available worker types and their descriptions
            - A schema for TaskMessage so it can produce valid subtasks

            Returns a list of TaskMessages ready for dispatch.
            '''
            ...

    Implementation notes:
    - The LLM should output structured JSON (list of subtasks)
    - Each subtask needs: worker_type, payload (matching that worker's input_schema),
      model_tier (or let the router decide)
    - Consider: should the decomposer also define dependencies between subtasks?
      (e.g., "run classifier AFTER extractor") — this would enable DAG execution
    - For now, PipelineOrchestrator handles sequential dependencies via YAML config
"""
from __future__ import annotations
