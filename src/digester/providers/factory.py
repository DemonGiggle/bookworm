from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import LLMProvider
from .openai_compatible import OpenAICompatibleProvider
from .openai_provider import OpenAIProvider


@dataclass
class ProviderSettings:
    provider_kind: str
    model: str
    api_key: str
    base_url: Optional[str] = None
    organization: Optional[str] = None


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
    raise ValueError("Unknown provider kind: {kind}".format(kind=settings.provider_kind))
