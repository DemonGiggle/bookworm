from __future__ import annotations

from typing import Optional

from .openai_provider import OpenAIProvider


class OpenAICompatibleProvider(OpenAIProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str,
        digest_temperature: float = 0.4,
        finalize_temperature: float = 0.1,
        finalize_max_output_tokens: int = 4096,
        finalize_reasoning_effort: Optional[str] = None,
        finalize_review_passes: int = 0,
        finalize_review_model: Optional[str] = None,
    ) -> None:
        if not base_url:
            raise ValueError("A base URL is required for openai-compatible providers.")
        super().__init__(
            model=model,
            api_key=api_key,
            base_url=base_url,
            digest_temperature=digest_temperature,
            finalize_temperature=finalize_temperature,
            finalize_max_output_tokens=finalize_max_output_tokens,
            finalize_reasoning_effort=finalize_reasoning_effort,
            finalize_review_passes=finalize_review_passes,
            finalize_review_model=finalize_review_model,
        )

    def validate_configuration(self) -> None:
        return None
