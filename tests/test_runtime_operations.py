import json
import tempfile
import unittest
from pathlib import Path

from contest_trade.operations.runtime import (
    RunAlreadyActiveError,
    RunJournal,
    RunLock,
    assess_run,
    atomic_write_json,
)


class RuntimeOperationsTests(unittest.TestCase):
    def test_atomic_health_write_and_journal_finish(self):
        with tempfile.TemporaryDirectory() as directory:
            health_path = Path(directory) / "last_run.json"
            atomic_write_json(health_path, {"status": "probe"})
            self.assertEqual(
                json.loads(health_path.read_text(encoding="utf-8"))["status"],
                "probe",
            )

            journal = RunJournal("2026-07-26 18:00:00", health_path)
            journal.start()
            payload = journal.finish(
                "success", "done", metrics={"output_signals": 1}
            )
            persisted = json.loads(health_path.read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "success")
        self.assertEqual(persisted["metrics"]["output_signals"], 1)
        self.assertIsNotNone(persisted["finished_at"])

    def test_run_lock_rejects_overlap(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / "run.lock"
            with RunLock(lock_path):
                with self.assertRaises(RunAlreadyActiveError):
                    with RunLock(lock_path):
                        self.fail("overlapping lock should not be acquired")

    def test_assess_run_classifies_success_degraded_and_failure(self):
        base_state = {
            "step_results": {
                "data_team": {"factors_count": 4, "failed_count": 0},
                "research_team": {"signals_count": 2, "failed_count": 0},
                "contest": {"aggregation_stats": {"output_count": 1}},
            }
        }
        status, _, metrics = assess_run(
            base_state, expected_data_agents=4, expected_research_agents=2
        )
        self.assertEqual(status, "success")
        self.assertEqual(metrics["output_signals"], 1)

        base_state["step_results"]["data_team"]["failed_count"] = 1
        status, _, _ = assess_run(
            base_state, expected_data_agents=4, expected_research_agents=2
        )
        self.assertEqual(status, "degraded")

        base_state["step_results"]["data_team"]["factors_count"] = 0
        status, _, _ = assess_run(
            base_state, expected_data_agents=4, expected_research_agents=2
        )
        self.assertEqual(status, "failed")


if __name__ == "__main__":
    unittest.main()
