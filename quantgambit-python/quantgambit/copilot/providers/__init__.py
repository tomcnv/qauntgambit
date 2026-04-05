"""LLM provider abstraction layer for the Trading Copilot."""

from quantgambit.copilot.providers.base import ModelProvider
from quantgambit.copilot.providers.openai import OpenAIProvider
from quantgambit.copilot.providers.anthropic import AnthropicProvider
from quantgambit.copilot.providers.azure_openai import AzureOpenAIProvider
from quantgambit.copilot.providers.factory import create_model_provider

__all__ = [
    "ModelProvider",
    "OpenAIProvider",
    "AnthropicProvider",
    "AzureOpenAIProvider",
    "create_model_provider",
]
