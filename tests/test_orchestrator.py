"""
Test orchestrator logic (unit tests, no infrastructure).

TODO: Add unit tests for OrchestratorActor (runner.py).
      OrchestratorActor is fully implemented with decompose/dispatch/
      collect/synthesize loop. Test cases should include:
      1. test_goal_decomposition — verify LLM output is parsed into TaskMessages
      2. test_subtask_dispatch — verify tasks are published to loom.tasks.incoming
      3. test_result_collection — verify results are matched by task_id
      4. test_synthesis — verify final result combines all worker outputs
      5. test_checkpoint_trigger — verify checkpoint fires at token threshold
      6. test_failed_subtask_handling — verify error propagation or retry

      PipelineOrchestrator unit tests live in test_pipeline.py (path resolution,
      condition evaluation, payload building).
"""
