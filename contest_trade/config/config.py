"""
config module for trade agent
"""
from pathlib import Path
import yaml
import os
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent.parent.resolve()


class ProjectConfig:

    def __init__(self, config_path: str | Path | None = None) -> None:
        market_type = 'CN-Stock'
        configured_path = config_path or os.environ.get("CONTEST_TRADE_CONFIG")
        yaml_path = Path(configured_path) if configured_path else PROJECT_ROOT.parent / "config.yaml"
        if not yaml_path.is_absolute():
            yaml_path = Path.cwd() / yaml_path
        yaml_path = yaml_path.resolve()
        if not yaml_path.is_file():
            raise FileNotFoundError(
                f"ContestTrade config not found: {yaml_path}; "
                "set CONTEST_TRADE_CONFIG to an explicit YAML file"
            )

        load_dotenv(yaml_path.parent / ".env")
        self.config_path = yaml_path

        with open(yaml_path, "r", encoding="utf-8") as fr:
            config = yaml.load(fr, Loader=yaml.FullLoader)
        for k in config:
            setattr(self, k, config[k])

        # 环境变量覆盖敏感配置
        self._load_secrets_from_env()

        # Store the market type for reference
        self.market_type = market_type

    # provider 识别 → 对应环境变量名。未识别的 URL 不会猜测或回退到其他密钥。
    _LLM_KEY_PROVIDERS = [
        ("longcat",     "LONGCAT_API_KEY"),
        ("sensenova",   "DEEPSEEK_API_KEY"),
        ("deepseek",    "DEEPSEEK_API_KEY"),
        ("minimax",     "MINIMAX_API_KEY"),
        ("dashscope",   "DASHSCOPE_API_KEY"),
    ]
    _VLM_KEY_PROVIDERS = _LLM_KEY_PROVIDERS

    def _resolve_key_from_base_url(self, base_url: str, providers: list):
        """根据 base_url 子串匹配环境变量名，未匹配时返回 None。"""
        url_lower = (base_url or "").lower()
        for substring, env_name in providers:
            if substring in url_lower:
                return env_name
        return None

    @staticmethod
    def _is_placeholder(value: str) -> bool:
        normalized = str(value or "").strip().upper()
        return not normalized or normalized.startswith("YOUR_")

    def _override_model_key(self, model_config: dict, providers: list):
        env_name = model_config.get("api_key_env") or self._resolve_key_from_base_url(
            model_config.get("base_url", ""), providers
        )
        if env_name and os.environ.get(env_name):
            model_config["api_key"] = os.environ[env_name]
        elif self._is_placeholder(model_config.get("api_key", "")):
            # 占位符不能被当作可用密钥传给上游 API。
            model_config["api_key"] = ""

    def _load_secrets_from_env(self):
        """从环境变量加载敏感配置，优先于 YAML 中的值。"""
        # 每个模型配置独立解析密钥，避免 LLM 的 key 被隐式复制给 thinking/VLM。
        if hasattr(self, "llm"):
            self._override_model_key(self.llm, self._LLM_KEY_PROVIDERS)
        if hasattr(self, "llm_thinking"):
            self._override_model_key(self.llm_thinking, self._LLM_KEY_PROVIDERS)

        # VLM API Key：复用 LLM 的 provider 表 + fallback
        if hasattr(self, "vlm"):
            self._override_model_key(self.vlm, self._VLM_KEY_PROVIDERS)

        # 搜索 Provider Keys：每个独立 env var，直接覆盖
        _SINGLE_KEY_OVERRIDES = [
            ("BOCHA_API_KEY",      "bocha_key"),
            ("SERP_API_KEY",       "serp_key"),
        ]
        for env_name, attr in _SINGLE_KEY_OVERRIDES:
            val = os.environ.get(env_name)
            if val and hasattr(self, attr):
                setattr(self, attr, val)

    def runtime_config_errors(self) -> list[str]:
        """Return actionable errors that would prevent an analysis run."""
        errors = []
        llm = getattr(self, "llm", {})
        provider = str(llm.get("provider", "openai")).lower()
        if provider != "ollama" and self._is_placeholder(llm.get("api_key", "")):
            env_name = llm.get("api_key_env") or "the configured model API key"
            errors.append(f"LLM API key is missing; set {env_name}")
        if not llm.get("model_name"):
            errors.append("llm.model_name is missing")
        if not getattr(self, "data_agents_config", None):
            errors.append("data_agents_config must contain at least one agent")
        research = getattr(self, "research_agent_config", {})
        if not research.get("tools"):
            errors.append("research_agent_config.tools must contain at least one tool")
        belief_path = PROJECT_ROOT / research.get("belief_list_path", "")
        if not belief_path.is_file():
            errors.append(f"research belief file does not exist: {belief_path}")
        return errors

    def validate_runtime(self) -> None:
        errors = self.runtime_config_errors()
        if errors:
            raise ValueError("Invalid runtime configuration: " + "; ".join(errors))

cfg = ProjectConfig()
