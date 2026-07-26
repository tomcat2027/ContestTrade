import json
import tempfile
import unittest
from pathlib import Path

from cli.static.report_template import (
    FinalReportGenerator,
    generate_final_report,
    generate_final_report_json,
)


class ReportGenerationTests(unittest.TestCase):
    def test_generates_markdown_and_json_with_aggregation_and_failures(self):
        final_state = {
            "trigger_time": "2026-07-26 15:00:00",
            "step_results": {
                "data_team": {
                    "factors_count": 3,
                    "failed_count": 1,
                    "failures": [{"agent_id": 3, "error": "source unavailable"}],
                    "elapsed_seconds": 1.0,
                },
                "research_team": {
                    "signals_count": 2,
                    "failed_count": 0,
                    "failures": [],
                    "elapsed_seconds": 2.0,
                },
                "contest": {
                    "best_signals": [
                        {
                            "has_opportunity": "yes",
                            "action": "buy",
                            "symbol_code": "600519.SH",
                            "symbol_name": "贵州茅台",
                            "probability": 80.0,
                            "aggregate_score": 0.8,
                            "action_consensus": 1.0,
                            "source_agents": ["agent_0"],
                            "evidence_list": [
                                {
                                    "description": "test evidence",
                                    "time": "2026-07-25",
                                    "from_source": "test",
                                }
                            ],
                            "limitations": ["test risk"],
                        }
                    ],
                    "aggregation_stats": {
                        "input_count": 2,
                        "output_count": 1,
                        "duplicate_count": 0,
                        "rejected_count": 1,
                        "filtered_count": 0,
                    },
                    "rejected_signals": [{"index": 1, "reason": "invalid"}],
                    "filtered_signals": [],
                },
            },
        }

        with tempfile.TemporaryDirectory() as directory:
            output_dir = Path(directory)
            markdown, markdown_path = generate_final_report(final_state, output_dir)
            json_path = generate_final_report_json(final_state, output_dir)
            payload = json.loads(json_path.read_text(encoding="utf-8"))

        self.assertTrue(markdown_path.name.endswith(".md"))
        self.assertIn("50.0% (1/2)", markdown)
        self.assertIn("数据 Agent 失败数", markdown)
        self.assertEqual(payload["aggregation_stats"]["output_count"], 1)
        self.assertEqual(payload["agent_failures"]["data"][0]["agent_id"], 3)
        self.assertEqual(len(payload["signals"]), 1)

    def test_report_without_trigger_time_uses_fallback_filename(self):
        final_state = {"step_results": {}}
        with tempfile.TemporaryDirectory() as directory:
            markdown, markdown_path = generate_final_report(
                final_state, Path(directory)
            )
        self.assertTrue(markdown_path.name.startswith("final_report_"))
        self.assertIn("ContestTrade v1.2.0", markdown)

    def test_interactive_view_builds_without_writing(self):
        markdown = FinalReportGenerator({"step_results": {}}).build_markdown_report()
        self.assertIn("最终分析报告", markdown)


if __name__ == "__main__":
    unittest.main()
