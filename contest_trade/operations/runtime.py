"""Runtime safety and health records for unattended analysis jobs."""

from __future__ import annotations

import json
import os
import socket
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from loguru import logger

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows is not a supported scheduler target.
    fcntl = None

from contest_trade.config.config import PROJECT_ROOT


RUNTIME_DIR = PROJECT_ROOT / "agents_workspace" / "runtime"
LOG_DIR = PROJECT_ROOT / "agents_workspace" / "logs"
LOCK_PATH = RUNTIME_DIR / "contesttrade.lock"
HEALTH_PATH = RUNTIME_DIR / "last_run.json"


class RunAlreadyActiveError(RuntimeError):
    """Raised when another scheduled analysis holds the process lock."""


def _timestamp() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Write a JSON document atomically so monitoring never sees a partial file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, path)


class RunLock:
    """Advisory non-blocking lock that prevents overlapping scheduled runs."""

    def __init__(self, path: Path = LOCK_PATH):
        self.path = path
        self._handle = None

    def __enter__(self) -> "RunLock":
        if fcntl is None:
            raise RuntimeError("Scheduled runs require a Unix-like system with fcntl")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a+", encoding="utf-8")
        try:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            self._handle.seek(0)
            owner = self._handle.read().strip() or "unknown owner"
            self._handle.close()
            self._handle = None
            raise RunAlreadyActiveError(
                f"another ContestTrade run is active ({owner})"
            ) from exc

        self._handle.seek(0)
        self._handle.truncate()
        self._handle.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "host": socket.gethostname(),
                    "acquired_at": _timestamp(),
                },
                ensure_ascii=False,
            )
        )
        self._handle.flush()
        os.fsync(self._handle.fileno())
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._handle is not None:
            fcntl.flock(self._handle.fileno(), fcntl.LOCK_UN)
            self._handle.close()
            self._handle = None


@dataclass
class RunHealth:
    run_id: str
    status: str
    trigger_time: str
    started_at: str
    finished_at: str | None = None
    duration_seconds: float | None = None
    pid: int = field(default_factory=os.getpid)
    host: str = field(default_factory=socket.gethostname)
    message: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    reports: Dict[str, str] = field(default_factory=dict)


class RunJournal:
    """Persist the latest run state for schedulers and health checks."""

    def __init__(self, trigger_time: str, path: Path = HEALTH_PATH):
        self.path = path
        self.started_monotonic = time.monotonic()
        self.health = RunHealth(
            run_id=uuid.uuid4().hex,
            status="running",
            trigger_time=trigger_time,
            started_at=_timestamp(),
        )

    def start(self) -> None:
        atomic_write_json(self.path, asdict(self.health))

    def finish(
        self,
        status: str,
        message: str,
        *,
        metrics: Dict[str, Any] | None = None,
        reports: Dict[str, Path] | None = None,
    ) -> Dict[str, Any]:
        self.health.status = status
        self.health.message = message
        self.health.finished_at = _timestamp()
        self.health.duration_seconds = round(
            time.monotonic() - self.started_monotonic, 3
        )
        self.health.metrics = metrics or {}
        self.health.reports = {
            name: str(path) for name, path in (reports or {}).items()
        }
        payload = asdict(self.health)
        atomic_write_json(self.path, payload)
        return payload


def configure_scheduled_logging(retention_days: int = 30) -> int:
    """Add a rotating file sink and return its Loguru sink identifier."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return logger.add(
        LOG_DIR / "scheduled_{time:YYYY-MM-DD}.log",
        rotation="00:00",
        retention=f"{max(1, retention_days)} days",
        encoding="utf-8",
        enqueue=True,
        backtrace=False,
        diagnose=False,
    )


def assess_run(
    final_state: Dict[str, Any],
    *,
    expected_data_agents: int,
    expected_research_agents: int,
) -> tuple[str, str, Dict[str, Any]]:
    """Classify a completed workflow as success, degraded, or failed."""
    steps = final_state.get("step_results", {})
    data = steps.get("data_team", {})
    research = steps.get("research_team", {})
    contest = steps.get("contest", {})
    aggregation = contest.get("aggregation_stats", {})

    metrics = {
        "data_factors": int(data.get("factors_count", 0)),
        "data_failures": int(data.get("failed_count", 0)),
        "research_signals": int(research.get("signals_count", 0)),
        "research_failures": int(research.get("failed_count", 0)),
        "output_signals": int(aggregation.get("output_count", 0)),
        "expected_data_agents": expected_data_agents,
        "expected_research_agents": expected_research_agents,
    }

    if metrics["data_factors"] == 0:
        return "failed", "no data agent produced a usable factor", metrics
    if expected_research_agents and metrics["research_failures"] >= expected_research_agents:
        return "failed", "all research agents failed", metrics

    failures = metrics["data_failures"] + metrics["research_failures"]
    missing_data_results = max(
        expected_data_agents
        - metrics["data_factors"]
        - metrics["data_failures"],
        0,
    )
    failures += missing_data_results
    if failures:
        return "degraded", f"completed with {failures} missing/failed agent result(s)", metrics
    return "success", "analysis and report generation completed", metrics


def read_health(path: Path = HEALTH_PATH) -> Dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        logger.warning(f"健康状态读取失败: {exc}")
        return {"status": "invalid", "message": str(exc)}
