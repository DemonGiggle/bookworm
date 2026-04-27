import json
from types import SimpleNamespace
from urllib.error import URLError

import httpx
import pytest
from openai import PermissionDeniedError

from digester.core.models import (
    ContentChunk,
    DigestBatchRequest,
    DigestConfig,
    SourceRef,
    TopicDigest,
)
from digester.providers import MockLLMProvider, ProviderSettings, create_provider
from digester.providers.ollama_provider import OllamaProvider, _normalize_base_url
from digester.providers.openai_provider import OpenAIProvider


def test_create_provider_builds_mock_llm_provider() -> None:
    provider = create_provider(
        ProviderSettings(
            provider_kind="mock-llm",
            model="fake-model",
        )
    )

    assert isinstance(provider, MockLLMProvider)
    assert provider.model == "fake-model"


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
    assert provider.timeout_seconds is None


def test_create_provider_passes_ollama_timeout() -> None:
    provider = create_provider(
        ProviderSettings(
            provider_kind="ollama",
            model="llama3.1",
            timeout_seconds=600,
        )
    )

    assert isinstance(provider, OllamaProvider)
    assert provider.timeout_seconds == 600


def test_normalize_base_url_preserves_scheme_and_default_port() -> None:
    assert _normalize_base_url("127.0.0.1", 11434) == "http://127.0.0.1:11434"
    assert _normalize_base_url("http://10.0.0.8", 11434) == "http://10.0.0.8:11434"
    assert _normalize_base_url("https://localhost:15000", 11434) == "https://localhost:15000"


def test_mock_llm_provider_generates_deterministic_placeholder_topics() -> None:
    provider = MockLLMProvider(model="fake-model")

    decision = provider.digest_batch(
        DigestBatchRequest(
            config=DigestConfig(),
            batch_number=1,
            total_batches=2,
            chunk_batch=[
                ContentChunk(
                    chunk_id="alpha-chunk-1",
                    source_id="alpha-notes",
                    source_path="/tmp/Alpha Notes.txt",
                    section_heading="Alpha Notes",
                    text="Alpha content",
                    source_ref=SourceRef(
                        source_id="alpha-notes",
                        source_path="/tmp/Alpha Notes.txt",
                        locator="full-document",
                    ),
                ),
                ContentChunk(
                    chunk_id="beta-chunk-1",
                    source_id="beta-notes",
                    source_path="/tmp/beta_notes.md",
                    section_heading="beta_notes",
                    text="Beta content",
                    source_ref=SourceRef(
                        source_id="beta-notes",
                        source_path="/tmp/beta_notes.md",
                        locator="full-document",
                    ),
                ),
            ],
            current_topics=[],
        )
    )

    assert decision.should_continue is True
    assert (
        decision.rationale
        == "MockLLM continues through the remaining batches to exercise the full pipeline."
    )
    assert [topic.slug for topic in decision.topic_updates] == ["mock-alpha-notes", "mock-beta-notes"]
    assert [topic.title for topic in decision.topic_updates] == ["Mock Alpha Notes", "Mock Beta Notes"]
    assert all(
        "without semantically parsing the document content" in topic.summary
        for topic in decision.topic_updates
    )
    assert all(topic.references for topic in decision.topic_updates)


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

    monkeypatch.setattr("digester.providers.ollama_provider.urlopen", lambda request: FakeResponse())

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

    def raise_error(request):
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


def test_ollama_provider_uses_explicit_timeout_when_configured(monkeypatch) -> None:
    provider = OllamaProvider(model="llama3.1", timeout_seconds=90)
    seen = {}

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
                                "topic_updates": [],
                                "should_continue": False,
                                "rationale": "Done.",
                            }
                        )
                    }
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout):
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("digester.providers.ollama_provider.urlopen", fake_urlopen)

    provider.digest_batch(
        DigestBatchRequest(
            config=DigestConfig(),
            batch_number=1,
            total_batches=1,
            chunk_batch=[],
            current_topics=[],
        )
    )

    assert seen["timeout"] == 90


def test_openai_provider_validate_configuration_reports_model_access(monkeypatch) -> None:
    provider = OpenAIProvider(model="gpt-5-nano", api_key="test-key")
    request = httpx.Request("GET", "https://api.openai.com/v1/models/gpt-5-nano")
    response = httpx.Response(
        403,
        request=request,
        json={
            "error": {
                "message": "Project `proj_test` does not have access to model `gpt-5-nano`",
                "code": "model_not_found",
            }
        },
    )
    error = PermissionDeniedError("Error code: 403", response=response, body=response.json())
    fake_client = SimpleNamespace(
        models=SimpleNamespace(retrieve=lambda model: (_ for _ in ()).throw(error))
    )
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

    with pytest.raises(ValueError, match="does not have access to model gpt-5-nano"):
        provider.validate_configuration()


def test_openai_provider_digest_batch_reports_model_access(monkeypatch) -> None:
    provider = OpenAIProvider(model="gpt-5-nano", api_key="test-key")
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(
        403,
        request=request,
        json={
            "error": {
                "message": "Project `proj_test` does not have access to model `gpt-5-nano`",
                "code": "model_not_found",
            }
        },
    )
    error = PermissionDeniedError("Error code: 403", response=response, body=response.json())
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: (_ for _ in ()).throw(error))
        )
    )
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

    with pytest.raises(ValueError, match="does not have access to model gpt-5-nano"):
        provider.digest_batch(
            DigestBatchRequest(
                config=DigestConfig(),
                batch_number=1,
                total_batches=1,
                chunk_batch=[],
                current_topics=[],
            )
        )
