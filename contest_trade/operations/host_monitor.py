"""Persistent host heartbeat and unclean-restart detection."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from contest_trade.operations.runtime import RUNTIME_DIR, atomic_write_json


HEARTBEAT_PATH = RUNTIME_DIR / "host_heartbeat.json"
INCIDENTS_PATH = RUNTIME_DIR / "host_incidents.jsonl"
DEFAULT_INTERVAL_SECONDS = 30


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _read_text(path: Path, default: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return default


def _memory_metrics() -> Dict[str, int]:
    values: Dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            key, raw = line.split(":", 1)
            if key in {"MemTotal", "MemAvailable", "SwapTotal", "SwapFree"}:
                values[key] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        pass
    return {
        "total_bytes": values.get("MemTotal", 0),
        "available_bytes": values.get("MemAvailable", 0),
        "swap_total_bytes": values.get("SwapTotal", 0),
        "swap_free_bytes": values.get("SwapFree", 0),
    }


def collect_snapshot() -> Dict[str, Any]:
    try:
        uptime_seconds = float(_read_text(Path("/proc/uptime"), "0").split()[0])
    except (ValueError, IndexError):
        uptime_seconds = 0.0
    try:
        load = [round(value, 3) for value in os.getloadavg()]
    except OSError:
        load = []
    disk = shutil.disk_usage(RUNTIME_DIR if RUNTIME_DIR.exists() else Path.cwd())
    return {
        "schema_version": 1,
        "state": "running",
        "recorded_at": _now(),
        "boot_id": _read_text(Path("/proc/sys/kernel/random/boot_id"), "unknown"),
        "hostname": socket.gethostname(),
        "pid": os.getpid(),
        "uptime_seconds": round(uptime_seconds, 1),
        "load_average": load,
        "memory": _memory_metrics(),
        "disk": {
            "total_bytes": disk.total,
            "free_bytes": disk.free,
            "used_bytes": disk.used,
        },
        "virtualization": {
            "vendor": _read_text(Path("/sys/class/dmi/id/sys_vendor")),
            "product": _read_text(Path("/sys/class/dmi/id/product_name")),
        },
    }


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else {}
    except (FileNotFoundError, OSError, json.JSONDecodeError, TypeError):
        return {}


def _append_incident(path: Path, incident: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(incident, ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def initialize_monitor(
    snapshot: Dict[str, Any],
    *,
    heartbeat_path: Path = HEARTBEAT_PATH,
    incidents_path: Path = INCIDENTS_PATH,
) -> Dict[str, Any] | None:
    previous = _read_json(heartbeat_path)
    incident = None
    if previous.get("state") == "running":
        boot_changed = previous.get("boot_id") != snapshot.get("boot_id")
        incident = {
            "schema_version": 1,
            "detected_at": snapshot["recorded_at"],
            "type": "unclean_restart" if boot_changed else "monitor_restarted",
            "reason": (
                "boot_id_changed_without_graceful_stop"
                if boot_changed
                else "monitor_process_restarted_without_graceful_stop"
            ),
            "previous_boot_id": previous.get("boot_id"),
            "current_boot_id": snapshot.get("boot_id"),
            "previous_last_heartbeat": previous.get("recorded_at"),
            "previous_uptime_seconds": previous.get("uptime_seconds"),
            "previous_load_average": previous.get("load_average"),
            "previous_memory": previous.get("memory"),
            "previous_disk": previous.get("disk"),
        }
        _append_incident(incidents_path, incident)
    atomic_write_json(heartbeat_path, snapshot)
    return incident


def mark_stopped(
    *, heartbeat_path: Path = HEARTBEAT_PATH, reason: str = "service_stopped"
) -> None:
    snapshot = _read_json(heartbeat_path) or collect_snapshot()
    snapshot.update({"state": "stopped", "recorded_at": _now(), "stop_reason": reason})
    atomic_write_json(heartbeat_path, snapshot)


def read_host_health(
    *,
    heartbeat_path: Path = HEARTBEAT_PATH,
    incidents_path: Path = INCIDENTS_PATH,
    incident_limit: int = 20,
) -> Dict[str, Any]:
    heartbeat = _read_json(heartbeat_path)
    incidents = []
    try:
        lines = incidents_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines[-max(1, incident_limit) :]:
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            incidents.append(value)

    age_seconds = None
    try:
        recorded_at = datetime.fromisoformat(str(heartbeat["recorded_at"]))
        age_seconds = max(
            0.0, (datetime.now(timezone.utc) - recorded_at.astimezone(timezone.utc)).total_seconds()
        )
    except (KeyError, TypeError, ValueError):
        pass
    healthy = heartbeat.get("state") == "running" and age_seconds is not None and age_seconds <= 90
    return {
        "status": "healthy" if healthy else "stale",
        "heartbeat_age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
        "heartbeat": heartbeat,
        "recent_incidents": incidents,
    }


def main() -> None:
    interval = max(5, int(os.environ.get("CONTESTTRADE_HOST_MONITOR_INTERVAL_SECONDS", DEFAULT_INTERVAL_SECONDS)))
    stop_event = threading.Event()

    def request_stop(signum, _frame):
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)
    initialize_monitor(collect_snapshot())
    try:
        while not stop_event.wait(interval):
            atomic_write_json(HEARTBEAT_PATH, collect_snapshot())
    finally:
        mark_stopped(reason="signal_received" if stop_event.is_set() else "monitor_exited")


if __name__ == "__main__":
    main()
