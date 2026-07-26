"""A-share market metadata backed by offline caches and AKShare."""

from __future__ import annotations

import json
import textwrap
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Dict, List

import pandas as pd
import yaml
from loguru import logger

from contest_trade.config.config import cfg


PROJECT_ROOT = Path(__file__).parent.parent.resolve()
CN_STOCK = "CN-Stock"


@dataclass
class MarketManagerConfig:
    target_markets: List[str]
    custom_symbols: List[Dict[str, str]]

    @classmethod
    def from_config_file(cls, config_path: str | None = None) -> "MarketManagerConfig":
        config_path = config_path or cfg.market_config_file
        config_file = Path(config_path)
        if not config_file.exists():
            config_file = PROJECT_ROOT / config_path
        if not config_file.exists():
            raise FileNotFoundError(f"配置文件未找到: {config_path}")

        with config_file.open("r", encoding="utf-8") as stream:
            config_data = yaml.safe_load(stream) or {}

        target_markets = config_data.get("target_markets", [])
        unsupported = [market for market in target_markets if market != CN_STOCK]
        if unsupported:
            raise ValueError(f"当前仅支持 {CN_STOCK}: {unsupported}")

        custom_symbols = []
        for market, symbols in (config_data.get("custom_symbols", {}) or {}).items():
            if market != CN_STOCK and symbols:
                raise ValueError(f"当前不支持自定义市场: {market}")
            custom_symbols.extend(
                {"market": market, "symbol": symbol} for symbol in (symbols or [])
            )
        return cls(target_markets=target_markets, custom_symbols=custom_symbols)


class MarketManager:
    """Provide the A-share symbol map, trading calendar, and prompt context."""

    def __init__(self, config: MarketManagerConfig):
        self.config = config
        self.cache_dir = Path(__file__).parent / "cache" / "market_manager"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.custom_symbols = [
            item["symbol"]
            for item in config.custom_symbols
            if item.get("market") == CN_STOCK and item.get("symbol")
        ]

    def get_target_symbol_context(self, trigger_time: str) -> str:
        del trigger_time
        if self.custom_symbols:
            availability = f"[{', '.join(self.custom_symbols)}]"
        else:
            availability = (
                "All symbols in the Chinese mainland A-share market. "
                "Examples: 000001.SZ, 600519.SH, 000858.SZ"
            )
        return textwrap.dedent(
            f"""
            You can invest in the following targets:

            market_name: {CN_STOCK}
            available_symbols: {availability}

            You can only select symbols from this market in investment decisions.
            """
        ).strip()

    def get_target_symbol_list(self, trigger_time: str, code_only: bool = True):
        symbols = self.get_market_symbols(CN_STOCK, trigger_time, full_market=True)
        if self.custom_symbols:
            symbols = symbols[symbols["ts_code"].isin(self.custom_symbols)]
        if code_only:
            return symbols["ts_code"].tolist()
        return [
            {"market": CN_STOCK, "symbol": row["ts_code"], "name": row["name"]}
            for row in symbols.to_dict(orient="records")
        ]

    def get_market_symbols(
        self,
        market: str,
        trigger_time: str,
        full_market: bool = False,
    ) -> pd.DataFrame:
        if market != CN_STOCK:
            raise ValueError(f"当前仅支持 {CN_STOCK}")
        stock_df = self._get_stock_basic_cache()
        if stock_df is None or stock_df.empty:
            raise RuntimeError("股票基础信息离线缓存不可用")
        target_date = trigger_time.split(" ")[0].replace("-", "")
        if "list_date" in stock_df.columns:
            stock_df = stock_df[stock_df["list_date"].astype(str) <= target_date]
        if self.custom_symbols and not full_market:
            stock_df = stock_df[stock_df["ts_code"].isin(self.custom_symbols)]
        return stock_df.copy()

    def get_stock_name_by_code(self, symbol: str, market: str = CN_STOCK) -> str:
        if market != CN_STOCK:
            raise ValueError(f"当前仅支持 {CN_STOCK}")
        _, code_to_name = self.get_stock_mapping(market)
        return code_to_name.get(symbol, symbol)

    def get_trade_date(self, market_name: str = CN_STOCK, verbose: bool = False):
        if market_name != CN_STOCK:
            raise ValueError(f"当前仅支持 {CN_STOCK}")

        cache_file = self.cache_dir / "trade_calendar.json"
        cached_dates = []
        try:
            if cache_file.exists():
                cached_dates = json.loads(cache_file.read_text(encoding="utf-8")).get(
                    "trade_dates", []
                )
                current_date = datetime.now().strftime("%Y%m%d")
                if cached_dates and cached_dates[-1] >= current_date:
                    return cached_dates
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.warning(f"交易日历缓存读取失败: {exc}")

        try:
            import akshare as ak

            trade_cal = ak.tool_trade_date_hist_sina()
            trade_dates = sorted(
                {
                    value.strftime("%Y%m%d")
                    if hasattr(value, "strftime")
                    else str(value).replace("-", "")
                    for value in trade_cal["trade_date"]
                    if (
                        value.strftime("%Y%m%d")
                        if hasattr(value, "strftime")
                        else str(value).replace("-", "")
                    )
                    >= "20240101"
                }
            )
            if trade_dates:
                self._save_trade_calendar_cache(trade_dates)
                return trade_dates
        except Exception as exc:
            logger.warning(f"AKShare 交易日历获取失败: {exc}")

        if cached_dates:
            if verbose:
                logger.warning("使用可用的旧交易日历缓存")
            return cached_dates
        raise RuntimeError("无法从 AKShare 或离线缓存获取 A 股交易日历")

    def fix_symbol_code(
        self,
        market_name: str,
        symbol_name: str,
        symbol_code: str,
        verbose: bool = False,
    ):
        if market_name != CN_STOCK:
            return symbol_name, symbol_code
        name_to_code, code_to_name = self.get_stock_mapping(market_name)
        mapped_code = name_to_code.get(symbol_name)
        if mapped_code and mapped_code != symbol_code:
            if verbose:
                logger.debug(f"set stock_code: {symbol_code} to {mapped_code}")
            symbol_code = mapped_code
        mapped_name = code_to_name.get(symbol_code)
        if not symbol_name and mapped_name:
            symbol_name = mapped_name
        elif mapped_name and mapped_name in symbol_name and mapped_name != symbol_name:
            symbol_name = mapped_name
        return symbol_name, symbol_code

    @lru_cache(maxsize=1)
    def get_stock_mapping(self, market_name: str = CN_STOCK):
        if market_name != CN_STOCK:
            raise ValueError(f"当前仅支持 {CN_STOCK}")
        stock_df = self._get_stock_basic_cache()
        if stock_df is None or stock_df.empty:
            raise RuntimeError("股票基础信息离线缓存不可用")

        name_to_code = {}
        code_to_name = {}
        for stock in stock_df.to_dict(orient="records"):
            name = str(stock.get("name", "")).strip()
            code = str(stock.get("ts_code", "")).strip()
            if not name or not code:
                continue
            name_to_code[name] = code
            name_to_code[name.split("-")[0]] = code
            code_to_name[code] = name.split("-")[0]
        name_to_code.update(self.get_total_namechange(market_name))
        return name_to_code, code_to_name

    def _get_stock_basic_cache(self):
        cache_path = self.cache_dir / "stock_basic_cache.json"
        try:
            if cache_path.exists():
                return pd.DataFrame(json.loads(cache_path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            logger.error(f"读取股票基础信息缓存失败: {exc}")
        return None

    def _save_trade_calendar_cache(self, trade_dates: List[str]):
        cache_file = self.cache_dir / "trade_calendar.json"
        payload = {
            "description": "A 股交易日历缓存",
            "generated_by": "AKShare ak.tool_trade_date_hist_sina()",
            "last_updated": datetime.now().strftime("%Y-%m-%d"),
            "date_range": f"{trade_dates[0]} ~ {trade_dates[-1]}",
            "trade_dates": trade_dates,
        }
        temporary = cache_file.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temporary.replace(cache_file)

    def get_total_namechange(self, market_name: str = CN_STOCK):
        if market_name != CN_STOCK:
            return {}
        cache_path = self.cache_dir / "namechange_data.json"
        if not cache_path.exists():
            raise FileNotFoundError(f"Required cache file not found: {cache_path}")
        return json.loads(cache_path.read_text(encoding="utf-8"))


GLOBAL_MARKET_CONFIG = MarketManagerConfig.from_config_file()
GLOBAL_MARKET_MANAGER = MarketManager(GLOBAL_MARKET_CONFIG)
