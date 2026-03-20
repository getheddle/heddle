"""Tests for Workshop FastAPI routes (workshop/app.py).

Tests the HTTP layer for baseline management, dead-letter replay log,
and eval scoring integration.  Uses FastAPI's TestClient with mock backends.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from loom.workshop.app import create_app


@pytest.fixture
def client(tmp_path):
    """Workshop TestClient with a temp config dir and in-memory DB."""
    configs_dir = tmp_path / "configs"
    workers_dir = configs_dir / "workers"
    workers_dir.mkdir(parents=True)

    # Create a minimal worker config
    worker_yaml = workers_dir / "test_worker.yaml"
    worker_yaml.write_text(
        "name: test_worker\n"
        "system_prompt: Summarize the text.\n"
        "input_schema:\n"
        "  type: object\n"
        "  required: [text]\n"
        "  properties:\n"
        "    text: {type: string}\n"
        "output_schema:\n"
        "  type: object\n"
        "  required: [summary]\n"
        "  properties:\n"
        "    summary: {type: string}\n"
        "default_model_tier: local\n"
    )

    # Create orchestrators dir (needed by ConfigManager)
    (configs_dir / "orchestrators").mkdir()

    app = create_app(
        configs_dir=str(configs_dir),
        db_path=":memory:",
        apps_dir=str(tmp_path / "apps"),
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health + basic routes
# ---------------------------------------------------------------------------


class TestBasicRoutes:
    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"

    def test_root_redirects(self, client):
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (302, 307)

    def test_workers_list(self, client):
        resp = client.get("/workers")
        assert resp.status_code == 200
        assert "test_worker" in resp.text

    def test_worker_detail(self, client):
        resp = client.get("/workers/test_worker")
        assert resp.status_code == 200

    def test_worker_not_found(self, client):
        resp = client.get("/workers/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Eval baseline routes
# ---------------------------------------------------------------------------


class TestEvalBaselines:
    def _create_eval_run(self, client):
        """Helper: manually insert an eval run via the DB."""
        app = client.app
        db = app.state.db
        run_id = db.save_eval_run("test_worker", "local", total_cases=1)
        db.save_eval_result(
            run_id=run_id,
            case_name="case_1",
            input_payload={"text": "hello"},
            passed=True,
            score=0.9,
        )
        db.update_eval_run(
            run_id,
            {"status": "completed", "passed_cases": 1, "failed_cases": 0},
        )
        return run_id

    def test_eval_detail_shows_no_baseline_initially(self, client):
        run_id = self._create_eval_run(client)
        resp = client.get(f"/workers/test_worker/eval/{run_id}")
        assert resp.status_code == 200

    def test_promote_baseline(self, client):
        run_id = self._create_eval_run(client)
        resp = client.post(
            f"/workers/test_worker/eval/{run_id}/promote-baseline",
            data={"description": "Test baseline"},
            follow_redirects=False,
        )
        assert resp.status_code == 303

        # Verify baseline was set
        db = client.app.state.db
        baseline = db.get_baseline("test_worker")
        assert baseline is not None
        assert baseline["run_id"] == run_id
        assert baseline["description"] == "Test baseline"

    def test_remove_baseline(self, client):
        run_id = self._create_eval_run(client)
        db = client.app.state.db
        db.promote_baseline("test_worker", run_id)

        resp = client.post(
            "/workers/test_worker/eval/remove-baseline",
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert db.get_baseline("test_worker") is None

    def test_eval_detail_with_baseline_comparison(self, client):
        db = client.app.state.db

        # Create baseline run
        baseline_id = db.save_eval_run("test_worker", "local", total_cases=1)
        db.save_eval_result(baseline_id, "case_1", {"text": "a"}, True, score=0.8)
        db.update_eval_run(
            baseline_id, {"status": "completed", "passed_cases": 1, "failed_cases": 0}
        )
        db.promote_baseline("test_worker", baseline_id)

        # Create new run
        new_id = db.save_eval_run("test_worker", "local", total_cases=1)
        db.save_eval_result(new_id, "case_1", {"text": "a"}, True, score=0.9)
        db.update_eval_run(new_id, {"status": "completed", "passed_cases": 1, "failed_cases": 0})

        resp = client.get(f"/workers/test_worker/eval/{new_id}")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Dead-letter replay log
# ---------------------------------------------------------------------------


class TestDeadLetterReplayLog:
    def test_dead_letters_page_shows_replay_log(self, client):
        resp = client.get("/dead-letters")
        assert resp.status_code == 200

    def test_replay_creates_audit_record(self, client):
        consumer = client.app.state.dead_letter_consumer
        entry = consumer.store(
            {"worker_type": "summarizer", "payload": {"text": "hi"}},
            "rate_limited",
            task_id="t-1",
            worker_type="summarizer",
        )
        assert consumer.replay_count() == 0

        # Replay via HTTP
        resp = client.post(
            "/dead-letters/0/replay",
            data={"entry_id": entry.id},
            follow_redirects=False,
        )
        assert resp.status_code == 303
        assert consumer.replay_count() == 1

        log = consumer.replay_log()
        assert log[0]["task_id"] == "t-1"
        assert log[0]["original_reason"] == "rate_limited"

    def test_clear_does_not_clear_replay_log(self, client):
        consumer = client.app.state.dead_letter_consumer
        entry = consumer.store({"x": 1}, "test", task_id="t-1")

        # Replay then clear
        client.post(
            "/dead-letters/0/replay",
            data={"entry_id": entry.id},
            follow_redirects=False,
        )
        client.post("/dead-letters/clear", follow_redirects=False)

        assert consumer.count() == 0
        assert consumer.replay_count() == 1  # Log preserved


# ---------------------------------------------------------------------------
# Eval run with scoring method in metadata
# ---------------------------------------------------------------------------


class TestEvalScoringMetadata:
    def test_eval_run_stores_scoring_method(self, client):
        """Eval runs should store scoring_method in metadata."""
        db = client.app.state.db
        run_id = db.save_eval_run(
            "test_worker",
            "local",
            total_cases=1,
            metadata={"scoring_method": "llm_judge"},
        )
        runs = db.get_eval_runs("test_worker")
        run = next(r for r in runs if r["id"] == run_id)
        assert run["id"] == run_id
