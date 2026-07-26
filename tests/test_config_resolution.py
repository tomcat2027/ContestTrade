import os
import unittest
from unittest.mock import patch

from contest_trade.config.config import ProjectConfig


class ConfigResolutionTests(unittest.TestCase):
    def setUp(self):
        self.config = ProjectConfig.__new__(ProjectConfig)

    def test_unknown_url_does_not_fall_back_to_unrelated_key(self):
        with patch.dict(os.environ, {"LONGCAT_API_KEY": "secret"}, clear=True):
            resolved = self.config._resolve_key_from_base_url(
                "https://unknown.example/v1", self.config._LLM_KEY_PROVIDERS
            )
        self.assertIsNone(resolved)

    def test_explicit_key_environment_wins(self):
        model = {
            "base_url": "https://unknown.example/v1",
            "api_key_env": "CUSTOM_MODEL_KEY",
            "api_key": "YOUR_KEY",
        }
        with patch.dict(os.environ, {"CUSTOM_MODEL_KEY": "configured"}, clear=True):
            self.config._override_model_key(model, self.config._LLM_KEY_PROVIDERS)
        self.assertEqual(model["api_key"], "configured")

    def test_placeholder_is_cleared_when_environment_is_missing(self):
        model = {
            "base_url": "https://unknown.example/v1",
            "api_key_env": "MISSING_KEY",
            "api_key": "YOUR_MODEL_KEY",
        }
        with patch.dict(os.environ, {}, clear=True):
            self.config._override_model_key(model, self.config._LLM_KEY_PROVIDERS)
        self.assertEqual(model["api_key"], "")

    def test_runtime_validation_reports_missing_llm_key(self):
        self.config.llm = {
            "provider": "openai",
            "model_name": "model",
            "api_key": "",
            "api_key_env": "MODEL_KEY",
        }
        self.config.data_agents_config = [{"agent_name": "data"}]
        self.config.research_agent_config = {
            "tools": ["tools.final_report.final_report"],
            "belief_list_path": "belief_list.json",
        }
        errors = self.config.runtime_config_errors()
        self.assertIn("LLM API key is missing; set MODEL_KEY", errors)


if __name__ == "__main__":
    unittest.main()
