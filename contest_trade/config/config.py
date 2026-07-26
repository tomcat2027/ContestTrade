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
        market_type = 'CN-Stock'
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

    # provider 识别 → 对应环境变量名
    # 优先级：列表中靠前的先匹配；都未命中则用最后的 fallback 列表
    _LLM_KEY_PROVIDERS = [
        ("longcat",     "LONGCAT_API_KEY"),
        ("sensenova",   "DEEPSEEK_API_KEY"),
        ("deepseek",    "DEEPSEEK_API_KEY"),
        ("minimax",     "MINIMAX_API_KEY"),
        ("dashscope",   "DASHSCOPE_API_KEY"),
    ]
    _VLM_KEY_PROVIDERS = _LLM_KEY_PROVIDERS  # VLM 复用同一张表
    _LLM_KEY_FALLBACK_CHAIN = [
        "LONGCAT_API_KEY",
        "DEEPSEEK_API_KEY",
        "MINIMAX_API_KEY",
        "DASHSCOPE_API_KEY",
    ]

    def _resolve_key_from_base_url(self, base_url: str, providers: list, fallback_chain: list):
        """根据 base_url 子串匹配返回环境变量名；未匹配时返回 fallback_chain 中第一个有值的 var 名（None 表示都无值）。"""
        url_lower = (base_url or "").lower()
        for substring, env_name in providers:
            if substring in url_lower:
                return env_name
        # 未匹配：按 fallback chain 找第一个有值的
        for env_name in fallback_chain:
            if os.environ.get(env_name):
                return env_name
        return None

    def _load_secrets_from_env(self):
        """从环境变量加载敏感配置，优先于 YAML 中的值。"""
        # LLM API Key：按 base_url 匹配 provider，再决定 env var
        if hasattr(self, "llm"):
            env_name = self._resolve_key_from_base_url(
                self.llm.get("base_url", ""),
                self._LLM_KEY_PROVIDERS,
                self._LLM_KEY_FALLBACK_CHAIN,
            )
            if env_name and os.environ.get(env_name):
                self.llm["api_key"] = os.environ[env_name]
                if hasattr(self, "llm_thinking"):
                    self.llm_thinking["api_key"] = os.environ[env_name]

        # VLM API Key：复用 LLM 的 provider 表 + fallback
        if hasattr(self, "vlm"):
            env_name = self._resolve_key_from_base_url(
                self.vlm.get("base_url", ""),
                self._VLM_KEY_PROVIDERS,
                self._LLM_KEY_FALLBACK_CHAIN,
            )
            if env_name and os.environ.get(env_name):
                self.vlm["api_key"] = os.environ[env_name]

        # 数据/搜索/US Provider Keys：每个独立 env var，直接覆盖
        _SINGLE_KEY_OVERRIDES = [
            ("TUSHARE_KEY",        "tushare_key"),
            ("BOCHA_API_KEY",      "bocha_key"),
            ("SERP_API_KEY",       "serp_key"),
        ]
        for env_name, attr in _SINGLE_KEY_OVERRIDES:
            val = os.environ.get(env_name)
            if val and hasattr(self, attr):
                setattr(self, attr, val)

cfg = ProjectConfig()

if __name__ == "__main__":
    print(f"Market Type: {cfg.market_type}")
    print(f"Data Agents Config: {cfg.data_agents_config}")
    print(f"Research Agent Config: {cfg.research_agent_config}")
    print(f"Market Config File: {cfg.market_config_file}")
    print(f"System Language: {cfg.system_language}")
    print(f"LLM Config: {cfg.llm}")
    print(f"Available attributes: {[attr for attr in dir(cfg) if not attr.startswith('_')]}")
