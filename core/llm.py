"""Model factory. One place decides which LLM backend an agent talks to.

    LLM_PROVIDER=deepseek   DEEPSEEK_API_KEY            model deepseek-chat (default)
    LLM_PROVIDER=tokenhub   TOKENHUB_API_KEY            TokenHub Singapore, OpenAI-compatible (hy3 / deepseek-v3.2)
    LLM_PROVIDER=ollama                                local loopback only, no paid API key

Models are OpenAI-compatible chat models; pydantic-ai's structured output rides on tool calling, which the selected model must
support. `LLM_MODEL` overrides the model name for the chosen provider.
"""
from __future__ import annotations

import os

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.deepseek import DeepSeekProvider
from pydantic_ai.providers.openai import OpenAIProvider

TOKENHUB_BASE_URL = "https://tokenhub-intl.tencentcloudmaas.com/v1"
DEFAULTS = {"deepseek": "deepseek-chat", "tokenhub": "hy3", "ollama": "qwen3:4b-instruct-2507-q4_K_M"}


def model_configured() -> bool:
    """Configuration readiness only; local server/model availability needs a live check."""
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    if provider == "ollama":
        return True
    key = {"deepseek": "DEEPSEEK_API_KEY", "tokenhub": "TOKENHUB_API_KEY"}.get(provider)
    return bool(key and os.environ.get(key, "").strip())


def make_model(role: str = "advocate"):
    """A pydantic-ai Model for `role` ("advocate" | "judge"); role lets LLM_MODEL_JUDGE override the judge's model."""
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    name = os.environ.get(f"LLM_MODEL_{role.upper()}") or os.environ.get("LLM_MODEL") or DEFAULTS[provider]
    if provider == "deepseek":
        return OpenAIChatModel(name, provider=DeepSeekProvider(api_key=os.environ["DEEPSEEK_API_KEY"]))
    if provider == "tokenhub":
        base = os.environ.get("TOKENHUB_BASE_URL", TOKENHUB_BASE_URL)
        return OpenAIChatModel(name, provider=OpenAIProvider(base_url=base, api_key=os.environ["TOKENHUB_API_KEY"]))
    if provider == "ollama":
        # Loopback only: local tests never use cloud credentials or paid inference.
        return OpenAIChatModel(name, provider=OpenAIProvider(base_url="http://127.0.0.1:11434/v1", api_key="ollama"))
    raise ValueError(f"unknown LLM_PROVIDER {provider!r}")


def describe_model() -> str:
    provider = os.environ.get("LLM_PROVIDER", "deepseek").lower()
    return f"{provider}:{os.environ.get('LLM_MODEL') or DEFAULTS.get(provider, '?')}"
