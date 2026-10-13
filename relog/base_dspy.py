import json
import os
from abc import ABC
from contextlib import contextmanager
from pathlib import Path

import dspy


class BaseDspy(ABC):
	DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config" / "llm_config.json"

	def __init__(
		self,
		model_name: str,
		cache: bool = False,
		temperature: float = 0.7,
		config_path: str | None = None,
		**kwargs,
	):
		self.model_name = model_name
		self.cache = cache
		self.temperature = temperature
		self.max_tokens = 20000
		config_path = config_path or os.environ.get("RELOG_LLM_CONFIG_PATH")
		self.config_path = Path(config_path) if config_path else self.DEFAULT_CONFIG_PATH

		api_config = self._load_config(model_name)

		model_name_lower = api_config["model_name"].lower()
		if api_config["provider"] == "openrouter" and "gpt" in model_name_lower:
			self.temperature = None
			self.max_tokens = 20000
			print(
				f"Detected OpenRouter GPT: setting temperature=None, max_tokens={self.max_tokens}"
			)
		if api_config["provider"] == "deepseek" and "deepseek" in model_name_lower:
			self.max_tokens = 8192
			print(f"Detected Deepseek model: setting max_tokens={self.max_tokens}")

		llm_kwargs = {
			"model": api_config["model_name"],
			"api_base": api_config["api_base"],
			"api_key": api_config["api_key"],
			"cache": cache,
		}

		llm_kwargs["temperature"] = self.temperature
		if self.max_tokens is not None:
			llm_kwargs["max_tokens"] = self.max_tokens

		self.llm = dspy.LM(**llm_kwargs)

		self._post_init(**kwargs)

	@contextmanager
	def use_model(self):
		with dspy.context(lm=self.llm):
			yield

	def _load_config(self, model_name: str) -> dict:
		with open(self.config_path, "r") as f:
			config = json.load(f)

		if model_name not in config:
			available_models = ", ".join(config.keys())
			raise ValueError(
				f"Model '{model_name}' not found in config file. "
				f"Available models: {available_models}"
			)

		model_config = config[model_name]

		required_fields = ["model_name", "api_base", "api_key", "provider"]
		missing_fields = [f for f in required_fields if f not in model_config]

		if missing_fields:
			raise ValueError(
				f"Model configuration for '{model_name}' is incomplete. "
				f"Missing fields: {missing_fields}"
			)

		return model_config

	def _post_init(self, **kwargs):
		pass
