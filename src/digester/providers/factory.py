from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import LLMProvider
from .mock_llm_provider import MockLLMProvider
from .ollama_provider import OllamaProvider
from .openai_compatible import OpenAICompatibleProvider
from .openai_provider import OpenAIProvider


@dataclass
class ProviderSettings:
    provider_kind: str
    model: str
    api_key: str = ""
    base_url: Optional[str] = None
    organization: Optional[str] = None
    ollama_host: str = "127.0.0.1"
    ollama_port: int = 11434


def create_provider(settings: ProviderSettings) -> LLMProvider:
    if settings.provider_kind == "openai":
        return OpenAIProvider(
            model=settings.model,
            api_key=settings.api_key,
            organization=settings.organization,
        )
    if settings.provider_kind == "openai-compatible":
        return OpenAICompatibleProvider(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url or "",
        )
    if settings.provider_kind == "ollama":
        return OllamaProvider(
            model=settings.model,
            host=settings.ollama_host,
            port=settings.ollama_port,
        )
    if settings.provider_kind == "mock-llm":
        return MockLLMProvider(model=settings.model)
    raise ValueError("Unknown provider kind: {kind}".format(kind=settings.provider_kind))
