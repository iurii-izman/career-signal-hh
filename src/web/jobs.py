"""Job manager — async task execution with progress for the local UI."""

from __future__ import annotations

import json
import os
import threading
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

# ── Job model ─────────────────────────────────────────────────────────


class Job:
    """An in-memory job that tracks execution state, progress, and logs."""

    __slots__ = (
        "id",
        "name",
        "status",
        "started_at",
        "finished_at",
        "progress",
        "message",
        "log_lines",
        "result",
        "error",
        "_cancel_flag",
    )

    def __init__(self, name: str) -> None:
        self.id = uuid.uuid4().hex[:12]
        self.name = name
        self.status: str = "queued"
        self.started_at: str | None = None
        self.finished_at: str | None = None
        self.progress: int = 0
        self.message: str = ""
        self.log_lines: list[dict[str, str]] = []
        self.result: Any = None
        self.error: str | None = None
        self._cancel_flag = False

    def add_log(self, msg: str, level: str = "info") -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "msg": msg,
            "level": level,
        }
        self.log_lines.append(entry)

    def set_progress(self, percent: int, message: str = "") -> None:
        self.progress = max(0, min(100, percent))
        self.message = message
        if message:
            self.add_log(message)

    def cancel(self) -> None:
        self._cancel_flag = True
        self.add_log("Cancellation requested", "warning")

    @property
    def cancelled(self) -> bool:
        return self._cancel_flag

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "progress": self.progress,
            "message": self.message,
            "log_lines": self.log_lines,
            "result": self.result,
            "error": self.error,
        }

    def sanitized_dict(self) -> dict[str, Any]:
        """Return dict with token values stripped from logs and error."""
        data = self.to_dict()
        token = os.getenv("HH_APP_ACCESS_TOKEN", "")
        if token:
            # Sanitize log lines
            sanitized_logs = []
            for entry in data.get("log_lines", []):
                msg = entry.get("msg", "")
                if token in msg:
                    msg = msg.replace(token, "[REDACTED]")
                sanitized_logs.append({**entry, "msg": msg})
            data["log_lines"] = sanitized_logs
            # Sanitize error
            if data.get("error") and token in data["error"]:
                data["error"] = data["error"].replace(token, "[REDACTED]")
            # Sanitize message
            if data.get("message") and token in data["message"]:
                data["message"] = data["message"].replace(token, "[REDACTED]")
        return data


# ── Job function type ──────────────────────────────────────────────────

JobFunc = Callable[[Job], Any]

# Heavy jobs that must be serialized (only one at a time)
HEAVY_JOB_PREFIXES = (
    "autopilot",
    "search",
    "export",
    "quality",
    "calibrate",
    "apply-pack",
)


# ── Job manager ────────────────────────────────────────────────────────


class JobManager:
    """Manages job lifecycle: creation, execution, cancellation, history.

    - Heavy jobs (autopilot, search, export, quality, calibration, apply-pack)
      are serialized: only one runs at a time.
    - Light jobs (health check, etc.) can run concurrently.
    - Jobs are stored in-memory.  Optionally persisted to data/ui_jobs.json.
    """

    _instance: JobManager | None = None

    def __init__(self) -> None:
        self._jobs: dict[str, Job] = {}
        self._heavy_lock = threading.Lock()
        self._heavy_running = False
        self._persist_path = Path("data/ui_jobs.json")

    @classmethod
    def get(cls) -> JobManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # ── Persistence ──────────────────────────────────────────────────

    def _persist(self) -> None:
        try:
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            jobs_data = [
                j.sanitized_dict()
                for j in sorted(
                    self._jobs.values(),
                    key=lambda j: j.started_at or "",
                    reverse=True,
                )[:50]
            ]
            self._persist_path.write_text(
                json.dumps(jobs_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    # ── Public API ───────────────────────────────────────────────────

    def start_job(self, name: str, func: JobFunc) -> Job:
        """Create and start a job. Returns the Job object immediately."""
        job = Job(name)
        self._jobs[job.id] = job

        is_heavy = name.startswith(HEAVY_JOB_PREFIXES)

        if is_heavy:
            with self._heavy_lock:
                if self._heavy_running:
                    job.status = "failed"
                    job.error = "Another heavy job is already running"
                    job.finished_at = datetime.now(timezone.utc).isoformat()
                    job.add_log(job.error, "error")
                    return job
                self._heavy_running = True

        thread = threading.Thread(
            target=self._run_job,
            args=(job, func, is_heavy),
            daemon=True,
        )
        thread.start()
        return job

    def get_job(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def list_jobs(self, limit: int = 20) -> list[dict[str, Any]]:
        jobs = sorted(
            self._jobs.values(),
            key=lambda j: j.started_at or j.finished_at or "",
            reverse=True,
        )
        return [j.sanitized_dict() for j in jobs[:limit]]

    def cancel_job(self, job_id: str) -> bool:
        job = self._jobs.get(job_id)
        if job is None:
            return False
        if job.status in ("running", "queued"):
            job.cancel()
            return True
        return False

    # ── Internal ────────────────────────────────────────────────────

    def _run_job(self, job: Job, func: JobFunc, is_heavy: bool) -> None:
        try:
            job.status = "running"
            job.started_at = datetime.now(timezone.utc).isoformat()
            job.add_log(f"Job started: {job.name}", "info")

            result = func(job)

            if job.cancelled:
                job.status = "cancelled"
                job.add_log("Job cancelled", "warning")
            else:
                job.status = "success"
                job.result = result
                if job.progress < 100:
                    job.set_progress(100, "Complete")
                job.add_log(f"Job completed: {job.name}", "info")

        except Exception as exc:
            job.status = "failed"
            job.error = str(exc)
            # Store full traceback in log but only summary in error
            tb = traceback.format_exc()
            job.add_log(f"Job failed: {exc}", "error")
            # Store traceback lines individually
            for line in tb.strip().split("\n"):
                job.add_log(line, "error")

        finally:
            job.finished_at = datetime.now(timezone.utc).isoformat()
            if is_heavy:
                with self._heavy_lock:
                    self._heavy_running = False
            self._persist()
