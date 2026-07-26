import unittest
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import patch

from cli.main import run_unattended_analysis


class _FakeCompany:
    def __init__(self):
        self.data_agents = {0: object()}
        self.research_agents = {0: object()}

    async def run_company(self, trigger_time):
        return {
            "trigger_time": trigger_time,
            "step_results": {
                "data_team": {"factors_count": 1, "failed_count": 0},
                "research_team": {"signals_count": 0, "failed_count": 0},
                "contest": {"aggregation_stats": {"output_count": 0}},
            },
        }


class _FakeJournal:
    def __init__(self, trigger_time):
        self.trigger_time = trigger_time

    def start(self):
        return None

    def finish(self, status, message, *, metrics=None, reports=None):
        return {
            "status": status,
            "message": message,
            "metrics": metrics or {},
            "reports": {name: str(path) for name, path in (reports or {}).items()},
        }


class UnattendedRunTests(unittest.TestCase):
    def test_guarded_run_returns_health_and_reports(self):
        with (
            patch("contest_trade.main.SimpleTradeCompany", _FakeCompany),
            patch(
                "contest_trade.operations.runtime.RunLock",
                return_value=nullcontext(),
            ),
            patch("contest_trade.operations.runtime.RunJournal", _FakeJournal),
            patch(
                "contest_trade.operations.runtime.configure_scheduled_logging",
                return_value=None,
            ),
            patch(
                "cli.main.generate_analysis_reports",
                return_value={"research_json": Path("report.json")},
            ),
        ):
            status, health = run_unattended_analysis(
                "2026-07-26 18:30:00", timeout_seconds=60
            )

        self.assertEqual(status, "success")
        self.assertEqual(health["metrics"]["data_factors"], 1)
        self.assertEqual(health["reports"]["research_json"], "report.json")


if __name__ == "__main__":
    unittest.main()
