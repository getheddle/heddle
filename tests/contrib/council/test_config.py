"""Tests for council config loading and validation."""

import tempfile

import pytest
import yaml
from pydantic import ValidationError

from loom.contrib.council.config import (
    CouncilConfig,
    load_council_config,
    validate_council_config,
)


def _minimal_config(**overrides):
    """Build a minimal valid council config dict."""
    cfg = {
        "name": "test_council",
        "agents": [
            {"name": "a1", "worker_type": "summarizer"},
            {"name": "a2", "worker_type": "reviewer"},
        ],
    }
    cfg.update(overrides)
    return cfg


class TestCouncilConfig:
    def test_minimal_valid(self):
        cfg = CouncilConfig(**_minimal_config())
        assert cfg.name == "test_council"
        assert len(cfg.agents) == 2
        assert cfg.protocol == "round_robin"
        assert cfg.max_rounds == 4

    def test_duplicate_agent_names_rejected(self):
        with pytest.raises(ValidationError, match="Duplicate"):
            CouncilConfig(
                **_minimal_config(
                    agents=[
                        {"name": "dup", "worker_type": "w1"},
                        {"name": "dup", "worker_type": "w2"},
                    ]
                )
            )

    def test_fewer_than_2_agents_rejected(self):
        with pytest.raises(ValidationError):
            CouncilConfig(
                **_minimal_config(
                    agents=[{"name": "only", "worker_type": "w1"}]
                )
            )

    def test_invalid_sees_transcript_from(self):
        with pytest.raises(ValidationError, match="unknown agent"):
            CouncilConfig(
                **_minimal_config(
                    agents=[
                        {
                            "name": "a1",
                            "worker_type": "w1",
                            "sees_transcript_from": ["nonexistent"],
                        },
                        {"name": "a2", "worker_type": "w2"},
                    ]
                )
            )

    def test_valid_sees_transcript_from(self):
        cfg = CouncilConfig(
            **_minimal_config(
                agents=[
                    {
                        "name": "a1",
                        "worker_type": "w1",
                        "sees_transcript_from": ["a2"],
                    },
                    {"name": "a2", "worker_type": "w2"},
                ]
            )
        )
        assert cfg.agents[0].sees_transcript_from == ["a2"]


class TestLoadCouncilConfig:
    def test_load_valid_yaml(self):
        raw = _minimal_config()
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".yaml", delete=False
        ) as f:
            yaml.dump(raw, f)
            path = f.name

        cfg = load_council_config(path)
        assert cfg.name == "test_council"

    def test_load_missing_file(self):
        with pytest.raises(FileNotFoundError):
            load_council_config("/nonexistent/path.yaml")


class TestValidateCouncilConfig:
    def test_valid_returns_empty(self):
        assert validate_council_config(_minimal_config()) == []

    def test_missing_name(self):
        raw = _minimal_config()
        del raw["name"]
        errors = validate_council_config(raw)
        assert any("name" in e for e in errors)

    def test_missing_agents(self):
        errors = validate_council_config({"name": "x"})
        assert any("agents" in e for e in errors)

    def test_too_few_agents(self):
        errors = validate_council_config(
            {"name": "x", "agents": [{"name": "one", "worker_type": "w"}]}
        )
        assert any("2 agents" in e for e in errors)

    def test_invalid_protocol(self):
        raw = _minimal_config(protocol="nonexistent")
        errors = validate_council_config(raw)
        assert any("protocol" in e.lower() for e in errors)

    def test_invalid_convergence_method(self):
        raw = _minimal_config(convergence={"method": "magic"})
        errors = validate_council_config(raw)
        assert any("method" in e.lower() for e in errors)

    def test_not_dict(self):
        assert validate_council_config("not a dict") == ["Config must be a dict"]
