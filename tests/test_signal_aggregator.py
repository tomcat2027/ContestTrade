import unittest

from contest_trade.utils.signal_aggregator import (
    SignalAggregatorConfig,
    aggregate_signals,
)


def make_signal(code="600519.SH", action="buy", probability=80, agent="agent_0"):
    return {
        "has_opportunity": "yes",
        "action": action,
        "symbol_code": code,
        "symbol_name": "测试股票",
        "probability": probability,
        "agent_name": agent,
        "evidence_list": [
            {
                "description": f"{agent} evidence",
                "time": "2026-07-25",
                "from_source": "test_source",
            }
        ],
        "limitations": ["测试风险"],
    }


class SignalAggregatorTests(unittest.TestCase):
    def test_merges_duplicate_symbols_and_sources(self):
        result = aggregate_signals(
            [make_signal(agent="agent_0"), make_signal(probability="70%", agent="agent_1")],
            "2026-07-26 09:00:00",
        )

        self.assertEqual(result["stats"]["duplicate_count"], 1)
        self.assertEqual(len(result["signals"]), 1)
        signal = result["signals"][0]
        self.assertEqual(signal["source_agents"], ["agent_0", "agent_1"])
        self.assertEqual(signal["probability"], 75.0)
        self.assertEqual(len(signal["evidence_list"]), 2)

    def test_rejects_ambiguous_action_conflict(self):
        result = aggregate_signals(
            [make_signal(action="buy"), make_signal(action="sell", agent="agent_1")],
            "2026-07-26 09:00:00",
        )

        self.assertEqual(result["signals"], [])
        self.assertEqual(result["filtered"][0]["reason"], "action_conflict")

    def test_rejects_invalid_or_future_only_evidence(self):
        invalid_code = make_signal(code="AAPL")
        future = make_signal(code="000001.SZ")
        future["evidence_list"][0]["time"] = "2026-07-27"

        result = aggregate_signals([invalid_code, future], "2026-07-26 09:00:00")

        self.assertEqual(result["signals"], [])
        self.assertEqual(
            {item["reason"] for item in result["rejected"]},
            {"invalid_symbol_code", "insufficient_evidence"},
        )

    def test_applies_score_threshold_and_top_n(self):
        config = SignalAggregatorConfig(top_n=1, min_score=0.55)
        result = aggregate_signals(
            [make_signal(code="600519.SH", probability=90), make_signal(code="000001.SZ", probability=60)],
            "2026-07-26 09:00:00",
            config,
        )

        self.assertEqual([signal["symbol_code"] for signal in result["signals"]], ["600519.SH"])
        self.assertTrue(any(item["reason"] == "outside_top_n" for item in result["filtered"]))


if __name__ == "__main__":
    unittest.main()
