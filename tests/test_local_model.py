"""Provider wiring tests; real local inference is reported separately."""
import pytest
from core.llm import make_model, model_configured, describe_model


def test_ollama_needs_no_cloud_key(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'ollama')
    monkeypatch.delenv('DEEPSEEK_API_KEY', raising=False)
    monkeypatch.delenv('TOKENHUB_API_KEY', raising=False)
    for name in ('LLM_MODEL', 'LLM_MODEL_JUDGE', 'LLM_MODEL_ADVOCATE'):
        monkeypatch.delenv(name, raising=False)
    assert model_configured()
    assert describe_model() == 'ollama:qwen3:4b-instruct-2507-q4_K_M'
    model = make_model('judge')
    assert model.model_name == 'qwen3:4b-instruct-2507-q4_K_M'
    assert str(model.client.base_url) == 'http://127.0.0.1:11434/v1/'


def test_ollama_respects_role_model(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'ollama')
    monkeypatch.setenv('LLM_MODEL_JUDGE', 'qwen3:4b')
    assert make_model('judge').model_name == 'qwen3:4b'


def test_unknown_provider_not_configured(monkeypatch):
    monkeypatch.setenv('LLM_PROVIDER', 'unknown')
    assert not model_configured()
