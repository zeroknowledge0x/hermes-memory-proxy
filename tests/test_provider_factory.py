"""Provider factory tests — PROVIDER_TYPE selects adapter without code change."""
from __future__ import annotations

import pytest

from memory_proxy.providers.credentials import CredentialProvider
from memory_proxy.providers.factory import build_provider, build_credentials
from memory_proxy.providers.anthropic_adapter import AnthropicAdapter
from memory_proxy.providers.openai_compatible_adapter import OpenAICompatibleAdapter


def _creds(key="k"):
    return build_credentials(api_key=key, oauth_file=None)


def test_factory_openai():
    p = build_provider("openai", "http://x/v1", _creds())
    assert isinstance(p, OpenAICompatibleAdapter)


def test_factory_anthropic():
    p = build_provider("anthropic", "http://x/v1", _creds())
    assert isinstance(p, AnthropicAdapter)


def test_factory_case_insensitive_and_default():
    assert isinstance(build_provider("OPENAI", "u", _creds()), OpenAICompatibleAdapter)
    assert isinstance(build_provider("", "u", _creds()), OpenAICompatibleAdapter)
    assert isinstance(build_provider(None, "u", _creds()), OpenAICompatibleAdapter)


def test_factory_unknown_raises():
    with pytest.raises(ValueError):
        build_provider("watson", "u", _creds())
