"""
Processor worker for non-LLM task processing.

ProcessorWorker delegates to a ProcessingBackend — any Python library,
rules engine, or external tool that isn't an LLM. Examples: Docling for
document extraction, ffmpeg for media, scikit-learn for classification.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import structlog

from loom.worker.base import TaskWorker

logger = structlog.get_logger()


class ProcessingBackend(ABC):
    """
    Generic processing backend interface for non-LLM workers.

    Implementations wrap a specific tool or library (Docling, ffmpeg, etc.)
    and translate between Loom's payload/output dicts and that tool's API.
    """

    @abstractmethod
    async def process(self, payload: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
        """
        Process a task payload.

        Args:
            payload: Validated input dict from TaskMessage.
            config: Full worker config dict (for backend-specific settings).

        Returns:
            {
                "output": dict,           # Structured output matching output_schema
                "model_used": str | None, # Identifier (e.g., "docling-v2", "ffmpeg-6.1")
            }
        """
        ...


class ProcessorWorker(TaskWorker):
    """
    Non-LLM stateless worker.

    Delegates processing to a ProcessingBackend instead of an LLM.
    Follows the same lifecycle as LLMWorker: validate input, process,
    validate output, publish result.
    """

    def __init__(
        self,
        actor_id: str,
        config_path: str,
        backend: ProcessingBackend,
        nats_url: str = "nats://nats:4222",
    ):
        super().__init__(actor_id, config_path, nats_url)
        self.backend = backend

    async def process(self, payload: dict[str, Any], metadata: dict[str, Any]) -> dict[str, Any]:
        logger.info("processor.processing", backend=type(self.backend).__name__)
        result = await self.backend.process(payload, self.config)
        return {
            "output": result["output"],
            "model_used": result.get("model_used"),
            "token_usage": {},
        }
