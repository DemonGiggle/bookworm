from __future__ import annotations

from .openai_provider import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    def __init__(self, model: str, api_key: str, base_url: str) -> None:
        if not base_url:
            raise ValueError("A base URL is required for openai-compatible providers.")
        super().__init__(model=model, api_key=api_key, base_url=base_url)
