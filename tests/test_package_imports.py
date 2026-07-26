import unittest
from unittest.mock import patch


class PackageImportTests(unittest.TestCase):
    def test_core_package_imports_without_path_mutation(self):
        from contest_trade.main import SimpleTradeCompany
        from contest_trade.tools.tool_utils import ToolManager

        self.assertIsNotNone(SimpleTradeCompany)
        self.assertIsNotNone(ToolManager)

    def test_legacy_tool_module_path_remains_compatible(self):
        from contest_trade.tools.tool_utils import ToolManager, ToolManagerConfig

        manager = ToolManager(
            ToolManagerConfig(["tools.final_report.final_report"])
        )
        self.assertIn("final_report", manager.get_all_tools())

    def test_search_tool_is_removed_without_search_credentials(self):
        from contest_trade.agents.research_agent import ResearchAgentConfig
        from contest_trade.config.config import cfg

        with (
            patch.object(cfg, "serp_key", ""),
            patch.object(cfg, "bocha_key", ""),
        ):
            config = ResearchAgentConfig(belief="test")
        self.assertFalse(
            any(
                path.endswith(".search_web.search_web")
                for path in config.tool_config.tool_paths
            )
        )


if __name__ == "__main__":
    unittest.main()
