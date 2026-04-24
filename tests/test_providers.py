import json
from urllib.error import URLError

import pytest

from digester.core.models import DigestBatchRequest, DigestConfig, SourceRef, TopicDigest
from digester.providers import ProviderSettings, create_provider
from digester.providers.ollama_provider import OllamaProvider, _normalize_base_url


def test_create_provider_builds_ollama_provider() -> None:
    provider = create_provider(
        ProviderSettings(
            provider_kind="ollama",
            model="llama3.1",
            ollama_host="192.168.1.40",
            ollama_port=11500,
        )
    )

    assert isinstance(provider, OllamaProvider)
    assert provider.base_url == "http://192.168.1.40:11500"


def test_normalize_base_url_preserves_scheme_and_default_port() -> None:
    assert _normalize_base_url("127.0.0.1", 11434) == "http://127.0.0.1:11434"
    assert _normalize_base_url("http://10.0.0.8", 11434) == "http://10.0.0.8:11434"
    assert _normalize_base_url("https://localhost:15000", 11434) == "https://localhost:15000"


def test_ollama_provider_digest_batch(monkeypatch) -> None:
    provider = OllamaProvider(model="llama3.1")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "topic_updates": [
                                    {
                                        "slug": "overview",
                                        "title": "Overview",
                                        "summary": "Condenses the current source.",
                                        "key_points": ["Uses Ollama locally"],
                                        "references": [
                                            {
                                                "source_id": "source",
                                                "source_path": "/tmp/source.txt",
                                                "locator": "full-document",
                                            }
                                        ],
                                    }
                                ],
                                "should_continue": False,
                                "rationale": "Enough evidence collected.",
                            }
                        )
                    }
                }
            ).encode("utf-8")

    monkeypatch.setattr("digester.providers.ollama_provider.urlopen", lambda request, timeout: FakeResponse())

    decision = provider.digest_batch(
        DigestBatchRequest(
            config=DigestConfig(),
            batch_number=1,
            total_batches=1,
            chunk_batch=[],
            current_topics=[],
        )
    )

    assert decision.should_continue is False
    assert decision.topic_updates[0].slug == "overview"


def test_ollama_provider_reports_connection_failure(monkeypatch) -> None:
    provider = OllamaProvider(model="llama3.1", host="192.168.1.50", port=11435)

    def raise_error(request, timeout):
        raise URLError("connection refused")

    monkeypatch.setattr("digester.providers.ollama_provider.urlopen", raise_error)

    with pytest.raises(ValueError, match="Unable to reach Ollama"):
        provider.finalize_topics(
            [
                TopicDigest(
                    slug="overview",
                    title="Overview",
                    summary="Summary",
                    key_points=["Point"],
                    references=[SourceRef(source_id="source", source_path="/tmp/source.txt", locator="full-document")],
                )
            ]
        )
