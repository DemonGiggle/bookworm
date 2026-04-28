from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .base import ImageAnalyzer
from .mock_image_analyzer import MockImageAnalyzer
from .ollama_image_analyzer import OllamaImageAnalyzer
from .openai_image_analyzer import OpenAIImageAnalyzer


@dataclass
class ImageAnalyzerSettings:
    analyzer_kind: str
    model: str
    api_key: str = ""
    base_url: Optional[str] = None
    organization: Optional[str] = None
    ollama_host: str = "127.0.0.1"
    ollama_port: int = 11434
    timeout_seconds: Optional[int] = None


def create_image_analyzer(settings: ImageAnalyzerSettings) -> ImageAnalyzer:
    if settings.analyzer_kind == "openai":
        return OpenAIImageAnalyzer(
            model=settings.model,
            api_key=settings.api_key,
            organization=settings.organization,
        )
    if settings.analyzer_kind == "openai-compatible":
        if not settings.base_url:
            raise ValueError("A base URL is required for openai-compatible image analyzers.")
        return OpenAIImageAnalyzer(
            model=settings.model,
            api_key=settings.api_key,
            base_url=settings.base_url,
            organization=settings.organization,
        )
    if settings.analyzer_kind == "mock-image":
        return MockImageAnalyzer(model=settings.model)
    if settings.analyzer_kind == "ollama":
        return OllamaImageAnalyzer(
            model=settings.model,
            host=settings.ollama_host,
            port=settings.ollama_port,
            timeout_seconds=settings.timeout_seconds,
        )
    raise ValueError("Unknown image analyzer kind: {kind}".format(kind=settings.analyzer_kind))
