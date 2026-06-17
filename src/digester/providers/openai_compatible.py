from __future__ import annotations

from .openai_provider import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        digest_temperature: float = 0.4,
        finalize_temperature: float = 0.1,
    ) -> None:
        if not base_url:
            raise ValueError("A base URL is required for openai-compatible providers.")
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            digest_temperature=digest_temperature,
            finalize_temperature=finalize_temperature,
        )

    def validate_configuration(self) -> None:
        return None
