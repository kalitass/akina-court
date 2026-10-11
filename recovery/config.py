"""Readiness of the original cloud providers; never creates a model."""
import os


def model_configured():
    key = {'deepseek': 'DEEPSEEK_API_KEY', 'tokenhub': 'TOKENHUB_API_KEY'}.get(os.environ.get('LLM_PROVIDER', 'deepseek').lower())
    return bool(key and os.environ.get(key, '').strip())
