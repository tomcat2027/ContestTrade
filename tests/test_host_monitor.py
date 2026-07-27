import json
import tempfile
import unittest
from pathlib import Path

from contest_trade.operations.host_monitor import initialize_monitor, read_host_health


class HostMonitorTests(unittest.TestCase):
    def test_detects_boot_change_without_graceful_stop(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            heartbeat = root / "heartbeat.json"
            incidents = root / "incidents.jsonl"
            previous = {
                "state": "running",
                "recorded_at": "2026-07-27T08:00:00+08:00",
                "boot_id": "old-boot",
                "uptime_seconds": 120,
                "load_average": [0.1, 0.2, 0.3],
            }
            heartbeat.write_text(json.dumps(previous), encoding="utf-8")
            current = {
                "state": "running",
                "recorded_at": "2026-07-27T08:05:00+08:00",
                "boot_id": "new-boot",
            }

            incident = initialize_monitor(
                current, heartbeat_path=heartbeat, incidents_path=incidents
            )

            self.assertEqual(incident["type"], "unclean_restart")
            saved = json.loads(heartbeat.read_text(encoding="utf-8"))
            self.assertEqual(saved["boot_id"], "new-boot")
            recorded = json.loads(incidents.read_text(encoding="utf-8"))
            self.assertEqual(recorded["previous_boot_id"], "old-boot")

    def test_read_health_ignores_malformed_incident_lines(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            heartbeat = root / "heartbeat.json"
            incidents = root / "incidents.jsonl"
            heartbeat.write_text(
                json.dumps(
                    {
                        "state": "running",
                        "recorded_at": "2999-01-01T00:00:00+00:00",
                        "boot_id": "boot",
                    }
                ),
                encoding="utf-8",
            )
            incidents.write_text('not-json\n{"type":"unclean_restart"}\n', encoding="utf-8")

            health = read_host_health(
                heartbeat_path=heartbeat, incidents_path=incidents
            )

            self.assertEqual(health["status"], "healthy")
            self.assertEqual(len(health["recent_incidents"]), 1)


if __name__ == "__main__":
    unittest.main()
