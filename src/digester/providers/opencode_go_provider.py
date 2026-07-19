from __future__ import annotations

from typing import Dict

from .openai_compatible import OpenAICompatibleProvider


OPENCODE_GO_BASE_URL = "https://opencode.ai/zen/go/v1"

# OpenCode Go currently exposes these models only through its Anthropic-style
# /messages endpoint. Bookworm must not silently send them to /chat/completions.
_MESSAGES_ONLY_MODELS = {
    "minimax-m3",
    "minimax-m2.7",
    "minimax-m2.5",
    "qwen3.7-max",
    "qwen3.7-plus",
    "qwen3.6-plus",
}


def normalize_opencode_go_model(model: str) -> str:
    normalized = model.strip()
    prefix = "opencode-go/"
    if normalized.startswith(prefix):
        normalized = normalized[len(prefix) :]
    if not normalized:
        raise ValueError("An OpenCode Go model ID is required.")
    return normalized


class OpenCodeGoProvider(OpenAICompatibleProvider):
    """OpenCode Go's OpenAI-compatible chat-completions provider."""

    def __init__(
        self,
        model: str,
        api_key: str,
        digest_temperature: float = 0.4,
        finalize_temperature: float = 0.1,
        finalize_max_output_tokens: int = 4096,
    ) -> None:
        normalized_model = normalize_opencode_go_model(model)
        if normalized_model.lower() in _MESSAGES_ONLY_MODELS:
            raise ValueError(
                "OpenCode Go model {model} uses the /messages API, which Bookworm does not "
                "support yet. Choose a Go model exposed through /chat/completions, such as "
                "kimi-k3, glm-5.2, or deepseek-v4-pro.".format(model=normalized_model)
            )
        super().__init__(
            model=normalized_model,
            api_key=api_key,
            base_url=OPENCODE_GO_BASE_URL,
            digest_temperature=digest_temperature,
            finalize_temperature=finalize_temperature,
            finalize_max_output_tokens=finalize_max_output_tokens,
            finalize_reasoning_effort=(
                "low" if normalized_model.lower().startswith("kimi-") else None
            ),
        )

    def _response_format(
        self, schema: Dict[str, object], schema_name: str
    ) -> Dict[str, object]:
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }
