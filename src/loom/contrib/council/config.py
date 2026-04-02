"""Council configuration loading and validation.

Loads council YAML configs into typed :class:`CouncilConfig` models.
Follows the same pattern as :func:`loom.core.config.load_config`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from loom.contrib.council.schemas import (
    AgentConfig,
    ConvergenceConfig,
    FacilitatorConfig,
)


class CouncilConfig(BaseModel):
    """Top-level council configuration, loaded from YAML."""

    name: str
    protocol: str = "round_robin"
    max_rounds: int = 4
    timeout_seconds: int = 600
    convergence: ConvergenceConfig = Field(default_factory=ConvergenceConfig)
    agents: list[AgentConfig] = Field(min_length=2)
    facilitator: FacilitatorConfig = Field(default_factory=FacilitatorConfig)

    @model_validator(mode="after")
    def _validate_agent_refs(self) -> CouncilConfig:
        names = {a.name for a in self.agents}

        # Check for duplicate names.
        if len(names) != len(self.agents):
            seen: set[str] = set()
            dupes: list[str] = []
            for a in self.agents:
                if a.name in seen:
                    dupes.append(a.name)
                seen.add(a.name)
            msg = f"Duplicate agent names: {dupes}"
            raise ValueError(msg)

        # Validate sees_transcript_from references.
        for a in self.agents:
            for ref in a.sees_transcript_from:
                if ref != "all" and ref not in names:
                    msg = (
                        f"Agent '{a.name}' references unknown agent "
                        f"'{ref}' in sees_transcript_from"
                    )
                    raise ValueError(msg)

        return self


def load_council_config(path: str | Path) -> CouncilConfig:
    """Load a council YAML config and return a validated model.

    Raises:
        FileNotFoundError: If *path* does not exist.
        pydantic.ValidationError: If the YAML content is invalid.
    """
    path = Path(path)
    with path.open() as f:
        raw = yaml.safe_load(f)
    return CouncilConfig(**raw)


def validate_council_config(raw: dict[str, Any]) -> list[str]:
    """Validate a raw dict as a council config, returning error strings.

    Returns an empty list if valid.  This mirrors the pattern of
    :func:`loom.core.config.validate_worker_config`.
    """
    errors: list[str] = []

    if not isinstance(raw, dict):
        return ["Config must be a dict"]

    if "name" not in raw:
        errors.append("Missing required key: 'name'")

    agents = raw.get("agents")
    if agents is None:
        errors.append("Missing required key: 'agents'")
    elif not isinstance(agents, list):
        errors.append("'agents' must be a list")
    elif len(agents) < 2:
        errors.append("At least 2 agents are required")

    protocol = raw.get("protocol", "round_robin")
    from loom.contrib.council.protocol import PROTOCOL_REGISTRY

    if protocol not in PROTOCOL_REGISTRY:
        errors.append(
            f"Unknown protocol '{protocol}'. "
            f"Available: {sorted(PROTOCOL_REGISTRY)}"
        )

    convergence = raw.get("convergence", {})
    if isinstance(convergence, dict):
        method = convergence.get("method", "none")
        if method not in {"llm_judge", "position_stability", "none"}:
            errors.append(
                f"convergence.method must be one of "
                f"'llm_judge', 'position_stability', 'none'; got '{method}'"
            )

    return errors
