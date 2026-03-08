"""
Loom message schemas. All inter-actor communication is typed.
Actors ONLY communicate through these message types.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class TaskPriority(str, Enum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class TaskStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRY = "retry"


class ModelTier(str, Enum):
    """Which model tier should handle this task."""
    LOCAL = "local"         # Small local model (Ollama, llama.cpp)
    STANDARD = "standard"   # Mid-tier API model
    FRONTIER = "frontier"   # Top-tier model (Claude Opus, GPT-4, etc.)


class TaskMessage(BaseModel):
    """Message sent TO a worker actor."""
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    parent_task_id: str | None = None          # Links subtask to orchestrator's goal
    worker_type: str                           # Which worker config to use
    payload: dict[str, Any]                    # Structured input per worker contract
    model_tier: ModelTier = ModelTier.STANDARD
    priority: TaskPriority = TaskPriority.NORMAL
    max_retries: int = 2
    retry_count: int = 0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskResult(BaseModel):
    """Message sent FROM a worker actor after processing."""
    task_id: str
    parent_task_id: str | None = None
    worker_type: str
    status: TaskStatus
    output: dict[str, Any] | None = None       # Structured output per worker contract
    error: str | None = None
    model_used: str | None = None               # Actual model that processed this
    token_usage: dict[str, int] = Field(default_factory=dict)  # prompt/completion tokens
    processing_time_ms: int = 0
    completed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class OrchestratorGoal(BaseModel):
    """Top-level goal submitted to an orchestrator."""
    goal_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    instruction: str                           # Natural language goal
    context: dict[str, Any] = Field(default_factory=dict)
    priority: TaskPriority = TaskPriority.NORMAL
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class CheckpointState(BaseModel):
    """Compressed orchestrator state for self-summarization."""
    goal_id: str
    original_instruction: str
    executive_summary: str                     # High-level status (always short)
    completed_tasks: list[dict[str, Any]]      # Key outcomes only, not full results
    pending_tasks: list[dict[str, Any]]        # What remains
    open_issues: list[str]                     # Conflicts, blockers, uncertainties
    decisions_made: list[str]                  # Important choices and rationale
    context_token_count: int                   # Tokens at time of checkpoint
    checkpoint_number: int
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
