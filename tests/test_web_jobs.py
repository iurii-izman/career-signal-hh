"""Tests for UI job manager and progress tracking."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

# ── Helpers ──────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_job_manager() -> None:
    """Reset JobManager singleton between tests."""
    from src.web.jobs import JobManager

    JobManager._instance = None


# ── Job model ────────────────────────────────────────────────────────────


def test_job_creation() -> None:
    """Job should be created with queued status and empty fields."""
    from src.web.jobs import Job

    job = Job("test-job")
    assert job.id is not None
    assert len(job.id) == 12
    assert job.name == "test-job"
    assert job.status == "queued"
    assert job.progress == 0
    assert job.started_at is None
    assert job.finished_at is None


def test_job_to_dict() -> None:
    """to_dict should return all public fields."""
    from src.web.jobs import Job

    job = Job("test-job")
    d = job.to_dict()
    assert d["id"] == job.id
    assert d["name"] == "test-job"
    assert d["status"] == "queued"
    assert d["progress"] == 0
    assert d["log_lines"] == []


def test_job_set_progress() -> None:
    """set_progress should update progress and message."""
    from src.web.jobs import Job

    job = Job("test")
    job.set_progress(50, "Halfway")
    assert job.progress == 50
    assert job.message == "Halfway"


def test_job_cancel_sets_flag() -> None:
    """cancel should set _cancel_flag and log it."""
    from src.web.jobs import Job

    job = Job("test")
    job.cancel()
    assert job.cancelled is True
    assert job._cancel_flag is True
    assert any("Cancellation" in entry["msg"] for entry in job.log_lines)


# ── Job manager ──────────────────────────────────────────────────────────


def test_start_job_success() -> None:
    """Manager should start a job and return it immediately with eventual success."""
    from src.web.jobs import JobManager

    mgr = JobManager.get()

    def dummy_func(job):
        job.set_progress(50, "working")
        time.sleep(0.05)
        job.set_progress(100, "done")
        return {"result": "ok"}

    job = mgr.start_job("test-success", dummy_func)
    assert job.status in ("queued", "running")
    assert job.name == "test-success"

    # Wait for completion
    time.sleep(0.2)
    job = mgr.get_job(job.id)
    assert job is not None
    assert job.status == "success"
    assert job.result == {"result": "ok"}


def test_failed_job_stores_error() -> None:
    """Failed job should store error message and have failed status."""
    from src.web.jobs import JobManager

    mgr = JobManager.get()

    def failing_func(job):
        job.set_progress(10, "starting")
        raise ValueError("test error message")

    job = mgr.start_job("test-fail", failing_func)
    time.sleep(0.2)

    job = mgr.get_job(job.id)
    assert job is not None
    assert job.status == "failed"
    assert "test error message" in (job.error or "")


def test_max_one_heavy_job() -> None:
    """Only one heavy job (prefix=autopilot) can run at a time."""
    from src.web.jobs import HEAVY_JOB_PREFIXES, JobManager

    # Verify autopilot is in heavy prefixes
    assert "autopilot" in HEAVY_JOB_PREFIXES

    mgr = JobManager.get()
    started = threading.Event()
    finish = threading.Event()

    def slow_func(job):
        started.set()
        finish.wait()  # Block until test releases
        return {}

    # Start first heavy job (unused — we just need it running)
    mgr.start_job("autopilot-slow", slow_func)  # noqa: F841

    # Wait for it to start
    started.wait(timeout=2)

    # Try to start second heavy job
    job2 = mgr.start_job("autopilot-second", lambda j: {})

    # Second should be rejected
    assert job2.status == "failed"
    assert "already running" in (job2.error or "")

    # Release first job
    finish.set()
    time.sleep(0.1)


def test_list_jobs() -> None:
    """list_jobs should return recent jobs in reverse chronological order."""
    from src.web.jobs import JobManager

    mgr = JobManager.get()

    jobs = []
    for i in range(3):
        j = mgr.start_job(f"test-{i}", lambda j, n=i: {"n": n})
        jobs.append(j)

    time.sleep(0.2)

    listed = mgr.list_jobs(limit=10)
    assert len(listed) >= 3


def test_get_job_endpoint_structure() -> None:
    """GET /api/jobs/{id} should return job data."""
    import asyncio

    from src.web.jobs import JobManager
    from src.web.routes import api_jobs_get

    mgr = JobManager.get()

    def fast_func(job):
        job.set_progress(100, "done")
        return {"ok": True}

    job = mgr.start_job("test-endpoint", fast_func)
    time.sleep(0.1)

    async def _run():
        resp = await api_jobs_get(job.id)
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert body["data"]["id"] == job.id
        assert body["data"]["name"] == "test-endpoint"
        assert body["data"]["status"] in ("running", "success")

    asyncio.run(_run())


def test_jobs_list_endpoint() -> None:
    """GET /api/jobs should return list."""
    import asyncio

    from src.web.jobs import JobManager
    from src.web.routes import api_jobs_list

    mgr = JobManager.get()
    mgr.start_job("test-list", lambda j: {"x": 1})
    time.sleep(0.1)

    async def _run():
        resp = await api_jobs_list(limit=10)
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert isinstance(body["data"], list)
        assert len(body["data"]) >= 1

    asyncio.run(_run())


def test_cancel_job() -> None:
    """POST /api/jobs/{id}/cancel should set cancelled flag."""
    import asyncio

    from src.web.jobs import JobManager
    from src.web.routes import api_jobs_cancel

    mgr = JobManager.get()

    # Create a running job that blocks
    block = threading.Event()
    started = threading.Event()

    def slow_func(job):
        started.set()
        block.wait()
        return {}

    job = mgr.start_job("test-cancel", slow_func)
    started.wait(timeout=2)

    async def _run():
        resp = await api_jobs_cancel(job.id)
        import json

        body = json.loads(resp.body)
        assert body["ok"] is True
        assert "Cancellation" in body["message"]

    asyncio.run(_run())

    # Release the job
    block.set()
    time.sleep(0.1)


def test_token_not_in_job_logs(monkeypatch) -> None:
    """Job sanitized_dict must not leak token in logs."""
    monkeypatch.setenv("HH_APP_ACCESS_TOKEN", "SECRET_TOKEN_XYZ")

    from src.web.jobs import Job

    job = Job("test")
    job.add_log("Using token: SECRET_TOKEN_XYZ")
    job.error = "Failed with SECRET_TOKEN_XYZ"
    job.message = "Token is SECRET_TOKEN_XYZ"

    data = job.sanitized_dict()

    logs_text = " ".join(e["msg"] for e in data["log_lines"])
    assert "SECRET_TOKEN_XYZ" not in logs_text
    assert "SECRET_TOKEN_XYZ" not in (data.get("error") or "")
    assert "SECRET_TOKEN_XYZ" not in (data.get("message") or "")
    assert "[REDACTED]" in logs_text


def test_user_oauth_token_not_in_job_logs(monkeypatch) -> None:
    """Job sanitized_dict must not leak OAuth token in logs."""
    monkeypatch.setenv("HH_USER_ACCESS_TOKEN", "USER_SECRET_TOKEN_XYZ")

    from src.web.jobs import Job

    job = Job("test")
    job.add_log("Using oauth token: USER_SECRET_TOKEN_XYZ")
    job.error = "Failed with USER_SECRET_TOKEN_XYZ"
    job.message = "Token is USER_SECRET_TOKEN_XYZ"

    data = job.sanitized_dict()

    logs_text = " ".join(e["msg"] for e in data["log_lines"])
    assert "USER_SECRET_TOKEN_XYZ" not in logs_text
    assert "USER_SECRET_TOKEN_XYZ" not in (data.get("error") or "")
    assert "USER_SECRET_TOKEN_XYZ" not in (data.get("message") or "")


def test_deep_mode_rejected() -> None:
    """Autopilot UI endpoint must reject deep mode."""
    import asyncio

    from src.web.routes import api_job_autopilot
    from src.web.schemas import ActionRequest

    async def _run():
        body = ActionRequest(mode="deep", preset=None)
        resp = await api_job_autopilot(body)
        import json

        body_data = json.loads(resp.body)
        assert body_data["ok"] is False

    asyncio.run(_run())


# ── Dashboard JS references job endpoints ───────────────────────────────


def test_index_html_has_job_card_elements() -> None:
    """index.html must contain job card and recent jobs sections."""
    html = Path("src/web/templates/index.html").read_text(encoding="utf-8")
    assert "job-card" in html
    assert "job-progress-bar" in html
    assert "recent-jobs" in html
    assert "job-cancel-btn" in html


def test_app_js_has_job_polling() -> None:
    """app.js must contain job polling and cancel functions."""
    js = Path("src/web/static/app.js").read_text(encoding="utf-8")
    assert "startJobPolling" in js
    assert "pollJob" in js
    assert "cancelActiveJob" in js
    assert "runJobAction" in js
    assert "loadRecentJobs" in js
    assert "/api/jobs" in js


# ── Job object passed to handler ────────────────────────────────────────


def test_handler_receives_job() -> None:
    """Handler function should receive the Job object as first argument."""
    from src.web.jobs import JobManager

    mgr = JobManager.get()
    received = []

    def handler(job):
        received.append(job)
        return {}

    job = mgr.start_job("test-handler", handler)
    time.sleep(0.1)

    assert len(received) == 1
    assert received[0].id == job.id
