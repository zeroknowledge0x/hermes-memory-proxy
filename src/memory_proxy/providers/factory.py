"""Provider factory — picks the adapter from PROVIDER_TYPE (D-002).

This is the ONLY place that knows about concrete adapters. The orchestrator
and API layer depend only on the ProviderAdapter interface.

Supported:
    "openai"    -> OpenAICompatibleAdapter   (OpenAI, Nous, Gemini, Ollama, vLLM, LM Studio)
    "anthropic" -> AnthropicAdapter
"""
from __future__ import annotations

from memory_proxy.providers.anthropic_adapter import AnthropicAdapter
from memory_proxy.providers.base import ProviderAdapter
from memory_proxy.providers.credentials import CredentialProvider
from memory_proxy.providers.openai_compatible_adapter import OpenAICompatibleAdapter


def build_credentials(*, api_key: str | None, oauth_file: str | None) -> CredentialProvider:
    return CredentialProvider(api_key=api_key, oauth_file=oauth_file)


def build_provider(provider_type: str, base_url: str, credentials: CredentialProvider) -> ProviderAdapter:
    pt = (provider_type or "openai").strip().lower()
    if pt == "openai":
        return OpenAICompatibleAdapter(base_url=base_url, credentials=credentials)
    if pt == "anthropic":
        # Anthropic currently only supports static API key (OAuth not wired)
        return AnthropicAdapter(base_url=base_url, api_key=credentials.get_token())
    raise ValueError(
        f"Unknown PROVIDER_TYPE={provider_type!r}. "
        f"Supported: openai, anthropic"
    )
