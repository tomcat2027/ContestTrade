"""
config module for trade agent
"""
from pathlib import Path
import yaml
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

# 加载 .env 文件（位于 ContestTrade/ 目录）
load_dotenv(PROJECT_ROOT.parent / ".env")


class ProjectConfig:

    def __init__(self) -> None:
        # Get market type from environment variable, default to CN-Stock
        market_type = os.environ.get('CONTEST_TRADE_MARKET', 'CN-Stock')
        
        # Choose config file based on market type
        if market_type == 'US-Stock':
            config_filename = "config_us.yaml"
        else:
            config_filename = "config.yaml"
        
        yaml_path = PROJECT_ROOT.parent / config_filename
        print(f"Loading config from: {yaml_path} (Market: {market_type})")

        with open(yaml_path, "r", encoding="utf-8") as fr:
            config = yaml.load(fr, Loader=yaml.FullLoader)
        for k in config:
            setattr(self, k, config[k])

        # 环境变量覆盖敏感配置
        self._load_secrets_from_env()

        # Store the market type for reference
        self.market_type = market_type

    def _load_secrets_from_env(self):
        """从环境变量加载敏感配置，优先于 YAML 中的值"""
        # 阿里云百炼 API Key
        if os.environ.get("DASHSCOPE_API_KEY"):
            dashscope_key = os.environ.get("DASHSCOPE_API_KEY")
            if hasattr(self, "llm"):
                self.llm["api_key"] = dashscope_key
            if hasattr(self, "llm_thinking"):
                self.llm_thinking["api_key"] = dashscope_key
            if hasattr(self, "vlm"):
                self.vlm["api_key"] = dashscope_key

        # Tushare Key
        if os.environ.get("TUSHARE_KEY"):
            self.tushare_key = os.environ.get("TUSHARE_KEY")

        # 搜索 API Keys
        if os.environ.get("BOCHA_API_KEY"):
            self.bocha_key = os.environ.get("BOCHA_API_KEY")
        if os.environ.get("SERP_API_KEY"):
            self.serp_key = os.environ.get("SERP_API_KEY")

        # 美股 API Keys
        if os.environ.get("FMP_KEY"):
            self.fmp_key = os.environ.get("FMP_KEY")
        if os.environ.get("FINNHUB_KEY"):
            self.finnhub_key = os.environ.get("FINNHUB_KEY")
        if os.environ.get("POLYGON_KEY"):
            self.polygon_key = os.environ.get("POLYGON_KEY")
        if os.environ.get("ALPHA_VANTAGE_KEY"):
            self.alpha_vantage_key = os.environ.get("ALPHA_VANTAGE_KEY")

cfg = ProjectConfig()

if __name__ == "__main__":
    print(f"Market Type: {cfg.market_type}")
    print(f"Data Agents Config: {cfg.data_agents_config}")
    print(f"Research Agent Config: {cfg.research_agent_config}")
    print(f"Market Config File: {cfg.market_config_file}")
    print(f"System Language: {cfg.system_language}")
    print(f"LLM Config: {cfg.llm}")
    print(f"Available attributes: {[attr for attr in dir(cfg) if not attr.startswith('_')]}")