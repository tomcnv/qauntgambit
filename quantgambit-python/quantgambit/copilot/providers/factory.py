"""Factory for creating the configured LLM provider from environment variables."""

from __future__ import annotations

import os

from quantgambit.copilot.providers.base import ModelProvider

SUPPORTED_PROVIDERS = ("openai", "anthropic", "azure_openai", "local")


def create_model_provider() -> ModelProvider:
    """Create the correct :class:`ModelProvider` based on environment variables.

    Environment variables
    ---------------------
    COPILOT_LLM_PROVIDER : str
        One of ``"openai"``, ``"anthropic"``, ``"azure_openai"``, ``"local"``.
    COPILOT_LLM_API_KEY : str
        API key for the chosen provider.
    COPILOT_LLM_MODEL : str
        Model name / deployment name.
    COPILOT_LLM_BASE_URL : str, optional
        Base URL for OpenAI-compatible or local endpoints.
    COPILOT_AZURE_ENDPOINT : str
        Azure OpenAI endpoint (required when provider is ``azure_openai``).
    COPILOT_AZURE_API_VERSION : str
        Azure API version (required when provider is ``azure_openai``).

    Raises
    ------
    ValueError
        If ``COPILOT_LLM_PROVIDER`` is not one of the supported providers.
    """
    provider_name = os.environ.get("COPILOT_LLM_PROVIDER", "").strip().lower()
    api_key = os.environ.get("COPILOT_LLM_API_KEY", "")
    model = os.environ.get("COPILOT_LLM_MODEL", "")
    base_url = os.environ.get("COPILOT_LLM_BASE_URL")
    azure_endpoint = os.environ.get("COPILOT_AZURE_ENDPOINT", "")
    azure_api_version = os.environ.get("COPILOT_AZURE_API_VERSION", "")

    # Treat DeepSeek and other OpenAI-compatible endpoints as "openai" when the
    # provider selector is omitted but the connection details are present.
    if not provider_name and (api_key or model or base_url):
        provider_name = "openai"

    if provider_name not in SUPPORTED_PROVIDERS:
        raise ValueError(
            f"Unsupported LLM provider: {provider_name!r}. "
            f"Supported providers: {', '.join(SUPPORTED_PROVIDERS)}"
        )

    if provider_name == "openai":
        from quantgambit.copilot.providers.openai import OpenAIProvider

        return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)

    if provider_name == "anthropic":
        from quantgambit.copilot.providers.anthropic import AnthropicProvider

        return AnthropicProvider(api_key=api_key, model=model)

    if provider_name == "azure_openai":
        from quantgambit.copilot.providers.azure_openai import AzureOpenAIProvider

        return AzureOpenAIProvider(
            api_key=api_key,
            model=model,
            endpoint=azure_endpoint,
            api_version=azure_api_version,
        )

    # "local" — uses OpenAI-compatible endpoint with custom base_url
    from quantgambit.copilot.providers.openai import OpenAIProvider

    return OpenAIProvider(api_key=api_key, model=model, base_url=base_url)
