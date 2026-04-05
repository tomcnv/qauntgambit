"""Unit tests for the provider factory."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from quantgambit.copilot.providers.base import ModelProvider
from quantgambit.copilot.providers.factory import SUPPORTED_PROVIDERS, create_model_provider
from quantgambit.copilot.providers.openai import OpenAIProvider
from quantgambit.copilot.providers.anthropic import AnthropicProvider
from quantgambit.copilot.providers.azure_openai import AzureOpenAIProvider


# -- helpers ---------------------------------------------------------------

def _env(provider: str, **overrides: str) -> dict[str, str]:
    """Build a minimal env-var dict for the given provider."""
    base: dict[str, str] = {
        "COPILOT_LLM_PROVIDER": provider,
        "COPILOT_LLM_API_KEY": "test-key",
        "COPILOT_LLM_MODEL": "test-model",
    }
    base.update(overrides)
    return base


# -- OpenAI ----------------------------------------------------------------

class TestOpenAIProvider:
    def test_returns_openai_provider(self) -> None:
        with mock.patch.dict(os.environ, _env("openai"), clear=True):
            provider = create_model_provider()
        assert isinstance(provider, OpenAIProvider)
        assert isinstance(provider, ModelProvider)

    def test_passes_base_url(self) -> None:
        env = _env("openai", COPILOT_LLM_BASE_URL="http://custom:8080/v1")
        with mock.patch.dict(os.environ, env, clear=True):
            provider = create_model_provider()
        assert isinstance(provider, OpenAIProvider)
        assert provider._base_url == "http://custom:8080/v1"

    def test_defaults_missing_provider_to_openai_compatible(self) -> None:
        env = {
            "COPILOT_LLM_API_KEY": "test-key",
            "COPILOT_LLM_MODEL": "deepseek-chat",
            "COPILOT_LLM_BASE_URL": "https://api.deepseek.com/v1",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            provider = create_model_provider()
        assert isinstance(provider, OpenAIProvider)
        assert provider._base_url == "https://api.deepseek.com/v1"


# -- Anthropic -------------------------------------------------------------

class TestAnthropicProvider:
    def test_returns_anthropic_provider(self) -> None:
        with mock.patch.dict(os.environ, _env("anthropic"), clear=True):
            provider = create_model_provider()
        assert isinstance(provider, AnthropicProvider)
        assert isinstance(provider, ModelProvider)


# -- Azure OpenAI ----------------------------------------------------------

class TestAzureOpenAIProvider:
    def test_returns_azure_provider(self) -> None:
        env = _env(
            "azure_openai",
            COPILOT_AZURE_ENDPOINT="https://my.openai.azure.com",
            COPILOT_AZURE_API_VERSION="2024-02-01",
        )
        with mock.patch.dict(os.environ, env, clear=True):
            provider = create_model_provider()
        assert isinstance(provider, AzureOpenAIProvider)
        assert isinstance(provider, ModelProvider)

    def test_passes_azure_config(self) -> None:
        env = _env(
            "azure_openai",
            COPILOT_AZURE_ENDPOINT="https://my.openai.azure.com/",
            COPILOT_AZURE_API_VERSION="2024-02-01",
        )
        with mock.patch.dict(os.environ, env, clear=True):
            provider = create_model_provider()
        assert isinstance(provider, AzureOpenAIProvider)
        assert provider._endpoint == "https://my.openai.azure.com"
        assert provider._api_version == "2024-02-01"


# -- Local (OpenAI-compatible) --------------------------------------------

class TestLocalProvider:
    def test_returns_openai_provider_for_local(self) -> None:
        env = _env("local", COPILOT_LLM_BASE_URL="http://localhost:1234/v1")
        with mock.patch.dict(os.environ, env, clear=True):
            provider = create_model_provider()
        assert isinstance(provider, OpenAIProvider)
        assert provider._base_url == "http://localhost:1234/v1"


# -- Unsupported provider --------------------------------------------------

class TestUnsupportedProvider:
    def test_raises_value_error_for_unknown(self) -> None:
        with mock.patch.dict(os.environ, _env("gemini"), clear=True):
            with pytest.raises(ValueError, match="Unsupported LLM provider"):
                create_model_provider()

    def test_error_lists_supported_providers(self) -> None:
        with mock.patch.dict(os.environ, _env("bad"), clear=True):
            with pytest.raises(ValueError) as exc_info:
                create_model_provider()
        msg = str(exc_info.value)
        for name in SUPPORTED_PROVIDERS:
            assert name in msg

    def test_raises_for_empty_provider(self) -> None:
        env = {
            "COPILOT_LLM_PROVIDER": "",
            "COPILOT_LLM_API_KEY": "test-key",
            "COPILOT_LLM_MODEL": "deepseek-chat",
            "COPILOT_LLM_BASE_URL": "https://api.deepseek.com/v1",
        }
        with mock.patch.dict(os.environ, env, clear=True):
            provider = create_model_provider()
        assert isinstance(provider, OpenAIProvider)

    def test_raises_for_missing_env_var(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError, match="Unsupported LLM provider"):
                create_model_provider()


# -- Case insensitivity ----------------------------------------------------

class TestCaseInsensitivity:
    def test_uppercase_provider_name(self) -> None:
        with mock.patch.dict(os.environ, _env("OPENAI"), clear=True):
            provider = create_model_provider()
        assert isinstance(provider, OpenAIProvider)

    def test_mixed_case_provider_name(self) -> None:
        with mock.patch.dict(os.environ, _env("Anthropic"), clear=True):
            provider = create_model_provider()
        assert isinstance(provider, AnthropicProvider)
