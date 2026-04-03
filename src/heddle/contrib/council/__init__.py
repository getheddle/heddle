"""Council — multi-round deliberation framework for Heddle.

Enables structured team discussions where multiple LLM-backed agents
deliberate on topics iteratively, each with their own context, role,
and perspective.  Supports pluggable discussion protocols, convergence
detection, and selective transcript visibility.

Usage::

    from heddle.contrib.council.runner import CouncilRunner
    from heddle.contrib.council.config import load_council_config

    config = load_council_config("configs/councils/example.yaml")
    runner = CouncilRunner(backends=my_backends)
    result = await runner.run("Should we adopt microservices?", config=config)
"""

from heddle.contrib.council.schemas import (
    AgentConfig,
    AgentTurn,
    ConvergenceResult,
    CouncilResult,
    RoundEntry,
    TranscriptEntry,
)

__all__ = [
    "AgentConfig",
    "AgentTurn",
    "ConvergenceResult",
    "CouncilResult",
    "RoundEntry",
    "TranscriptEntry",
]
