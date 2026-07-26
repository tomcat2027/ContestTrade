import tempfile
import unittest
from pathlib import Path

from contest_trade.utils.market_manager import (
    CN_STOCK,
    MarketManagerConfig,
    GLOBAL_MARKET_MANAGER,
)


class MarketManagerTests(unittest.TestCase):
    def test_package_import_and_offline_symbol_mapping(self):
        name_to_code, code_to_name = GLOBAL_MARKET_MANAGER.get_stock_mapping()
        self.assertEqual(name_to_code["贵州茅台"], "600519.SH")
        self.assertEqual(code_to_name["600519.SH"], "贵州茅台")

    def test_config_rejects_removed_markets(self):
        with tempfile.TemporaryDirectory() as directory:
            config_path = Path(directory) / "market.yaml"
            config_path.write_text(
                "target_markets:\n  - US-Stock\ncustom_symbols: {}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "当前仅支持"):
                MarketManagerConfig.from_config_file(str(config_path))

    def test_market_query_rejects_removed_markets(self):
        with self.assertRaisesRegex(ValueError, CN_STOCK):
            GLOBAL_MARKET_MANAGER.get_market_symbols(
                "US-Stock", "2026-07-26 12:00:00"
            )


if __name__ == "__main__":
    unittest.main()
