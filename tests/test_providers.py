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
    DigestDecision,
    SourceRef,
    TopicDigest,
)
from digester.providers import MockLLMProvider, ProviderSettings, create_provider
from digester.providers.ollama_provider import OllamaProvider, _normalize_base_url
from digester.providers.parsing import parse_finalized_topics
from digester.providers.openai_provider import OpenAIProvider


class RecordingVerboseReporter:
    def __init__(self) -> None:
        self.messages = []
        self.verbose_level = 1

    def update(self, message: str) -> None:
        self.messages.append(("update", message))

    def persist(self, message: str) -> None:
        self.messages.append(("persist", message))

    def verbose(self, message: str) -> None:
        self.messages.append(("verbose", message))

    def verbosity(self) -> int:
        return self.verbose_level

    def clear(self) -> None:
        self.messages.append(("clear", ""))


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
    assert all(topic.routing_description.startswith("Use this skill when validating") for topic in decision.topic_updates)
    assert all(
        "without semantically parsing the document content" in topic.summary
        for topic in decision.topic_updates
    )
    assert all(topic.workflow_notes for topic in decision.topic_updates)
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
                                        "routing_description": "Use this skill when reviewing the locally digested overview.",
                                        "summary": "Condenses the current source.",
                                        "key_points": ["Uses Ollama locally"],
                                        "workflow_notes": ["Validate the local model output before reuse."],
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
    assert (
        decision.topic_updates[0].routing_description
        == "Use this skill when reviewing the locally digested overview."
    )
    assert decision.topic_updates[0].workflow_notes == ["Validate the local model output before reuse."]


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
                    routing_description="Use this skill when reviewing the finalized overview guidance.",
                    summary="Summary",
                    key_points=["Point"],
                    workflow_notes=["Re-run the provider once Ollama connectivity is restored."],
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


def test_parse_finalized_topics_preserves_structured_skill_fields() -> None:
    parsed = parse_finalized_topics(
        {
            "topics": [
                {
                    "slug": "overview",
                    "title": "Overview",
                    "routing_description": "Use this skill when reviewing the finalized overview guidance.",
                    "summary": "Condenses the finalized source.",
                    "key_points": ["Check the finalized guidance before editing."],
                    "workflow_notes": ["Validate the cited source before applying the summarized workflow."],
                    "references": [
                        {
                            "source_id": "source",
                            "source_path": "/tmp/source.txt",
                            "locator": "full-document",
                        }
                    ],
                }
            ]
        }
    )

    assert len(parsed) == 1
    assert parsed[0].routing_description == "Use this skill when reviewing the finalized overview guidance."
    assert parsed[0].workflow_notes == [
        "Validate the cited source before applying the summarized workflow."
    ]


def test_parse_finalized_topics_coerces_text_fields_without_character_splitting() -> None:
    parsed = parse_finalized_topics(
        {
            "topics": [
                {
                    "slug": "overview",
                    "title": "Overview",
                    "routing_description": "Use this skill when reviewing finalized guidance.",
                    "summary": "Condenses the finalized source.",
                    "key_points": "Check the generated guidance before editing.",
                    "workflow_notes": ["h", "e", "l", "l", "o"],
                    "references": [
                        {
                            "source_id": "source",
                            "source_path": "/tmp/source.txt",
                            "locator": "full-document",
                        }
                    ],
                }
            ]
        }
    )

    assert parsed[0].key_points == ["Check the generated guidance before editing."]
    assert parsed[0].workflow_notes == ["hello"]


def test_digest_decision_coerces_text_fields_without_character_splitting() -> None:
    decision = DigestDecision.from_payload(
        {
            "topic_updates": [
                {
                    "slug": "overview",
                    "title": "Overview",
                    "routing_description": "Use this skill when reviewing batch guidance.",
                    "summary": "Condenses the batch source.",
                    "key_points": ["c", "h", "e", "c", "k"],
                    "workflow_notes": "Validate the generated guidance before editing.",
                    "references": [],
                }
            ],
            "should_continue": False,
            "rationale": "Done.",
        },
        fallback_refs=[
            SourceRef(
                source_id="source",
                source_path="/tmp/source.txt",
                locator="full-document",
            )
        ],
    )

    assert decision.topic_updates[0].key_points == ["check"]
    assert decision.topic_updates[0].workflow_notes == [
        "Validate the generated guidance before editing."
    ]


def test_parse_finalized_topics_restores_missing_references_from_fallback_topic() -> None:
    fallback_ref = SourceRef(
        source_id="source",
        source_path="/tmp/source.txt",
        locator="full-document",
    )

    parsed = parse_finalized_topics(
        {
            "topics": [
                {
                    "slug": "overview",
                    "title": "Overview",
                    "routing_description": "Use this skill when reviewing the finalized overview guidance.",
                    "summary": "Condenses the finalized source into reusable implementation guidance.",
                    "key_points": ["Check the finalized guidance before editing."],
                    "workflow_notes": ["Validate the cited source before applying the workflow."],
                    "references": [],
                }
            ]
        },
        fallback_topics=[
            TopicDigest(
                slug="overview",
                title="Overview",
                routing_description="Use this skill when reviewing the draft overview guidance.",
                summary="Draft summary",
                key_points=[],
                references=[fallback_ref],
            )
        ],
    )

    assert parsed[0].references == [fallback_ref]


def test_parse_finalized_topics_treats_null_routing_description_as_empty_string() -> None:
    parsed = parse_finalized_topics(
        {
            "topics": [
                {
                    "slug": "overview",
                    "title": "Overview",
                    "routing_description": None,
                    "summary": "Condenses the finalized source.",
                    "key_points": ["Check the finalized guidance before editing."],
                    "workflow_notes": [],
                    "references": [],
                }
            ]
        }
    )

    assert len(parsed) == 1
    assert parsed[0].routing_description == ""


def test_parse_finalized_topics_requires_topics_list() -> None:
    with pytest.raises(ValueError, match="must contain a topics list"):
        parse_finalized_topics({})


def test_parse_finalized_topics_rejects_empty_valid_topic_list() -> None:
    with pytest.raises(ValueError, match="contained no valid topics"):
        parse_finalized_topics({"topics": [{"slug": "", "title": ""}]})


def test_ollama_provider_verbose_logging_reports_request_and_response(monkeypatch) -> None:
    provider = OllamaProvider(model="llama3.1")
    reporter = RecordingVerboseReporter()
    provider.set_progress_reporter(reporter)
    timing_points = iter([10.0, 12.5])

    long_system_prompt = "S" * 300
    long_user_prompt = "U" * 280
    response_content = json.dumps(
        {
            "topic_updates": [],
            "should_continue": False,
            "rationale": "Done.",
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"message": {"content": response_content}}).encode("utf-8")

    monkeypatch.setattr("digester.providers.ollama_provider.urlopen", lambda request: FakeResponse())
    monkeypatch.setattr("digester.providers.ollama_provider.perf_counter", lambda: next(timing_points))

    payload = provider._complete_json(
        system_prompt=long_system_prompt,
        user_prompt=long_user_prompt,
    )

    verbose_messages = [message for kind, message in reporter.messages if kind == "verbose"]
    assert payload["rationale"] == "Done."
    assert any("sending 580 chars to Ollama model llama3.1" in message for message in verbose_messages)
    assert any("request preview" in message and "[omitted 60 chars]" in message for message in verbose_messages)
    assert any("returned {count} chars in 2.50s".format(count=len(response_content)) in message for message in verbose_messages)
    assert any("response preview" in message for message in verbose_messages)


def test_ollama_provider_retries_once_after_invalid_model_json(monkeypatch) -> None:
    provider = OllamaProvider(model="llama3.1")
    responses = iter(
        [
            '{"topic_updates": [], "should_continue": false',
            json.dumps(
                {
                    "topic_updates": [],
                    "should_continue": False,
                    "rationale": "Done.",
                }
            ),
        ]
    )

    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"message": {"content": self.content}}).encode("utf-8")

    def fake_urlopen(request):
        return FakeResponse(next(responses))

    monkeypatch.setattr("digester.providers.ollama_provider.urlopen", fake_urlopen)

    payload = provider._complete_json(
        system_prompt="system prompt",
        user_prompt="user prompt",
    )

    assert payload["rationale"] == "Done."


def test_openai_provider_verbose_logging_reports_request_and_response(monkeypatch) -> None:
    provider = OpenAIProvider(model="gpt-5-nano", api_key="test-key")
    reporter = RecordingVerboseReporter()
    provider.set_progress_reporter(reporter)
    timing_points = iter([100.0, 101.75])

    response_content = json.dumps(
        {
            "topic_updates": [],
            "should_continue": False,
            "rationale": "Enough context collected.",
        }
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=response_content))]
                )
            )
        )
    )
    monkeypatch.setattr(provider, "_client", lambda: fake_client)
    monkeypatch.setattr("digester.providers.openai_provider.perf_counter", lambda: next(timing_points))

    payload = provider._complete_json(
        system_prompt="system prompt",
        user_prompt="user prompt " + ("x" * 260),
    )

    verbose_messages = [message for kind, message in reporter.messages if kind == "verbose"]
    assert payload["rationale"] == "Enough context collected."
    assert any("sending 285 chars to OpenAI model gpt-5-nano" in message for message in verbose_messages)
    assert any("request preview" in message and "[omitted 32 chars]" in message for message in verbose_messages)
    assert any("returned {count} chars in 1.75s".format(count=len(response_content)) in message for message in verbose_messages)
    assert any("response preview" in message for message in verbose_messages)


def test_openai_provider_double_verbose_logging_keeps_full_body(monkeypatch) -> None:
    provider = OpenAIProvider(model="gpt-5-nano", api_key="test-key")
    reporter = RecordingVerboseReporter()
    reporter.verbose_level = 2
    provider.set_progress_reporter(reporter)
    timing_points = iter([1.0, 1.25])
    user_prompt = "user prompt " + ("x" * 260)
    response_content = json.dumps(
        {
            "topic_updates": [],
            "should_continue": False,
            "rationale": "Enough context collected.",
        }
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=response_content))]
                )
            )
        )
    )
    monkeypatch.setattr(provider, "_client", lambda: fake_client)
    monkeypatch.setattr("digester.providers.openai_provider.perf_counter", lambda: next(timing_points))

    provider._complete_json(system_prompt="system prompt", user_prompt=user_prompt)

    verbose_messages = [message for kind, message in reporter.messages if kind == "verbose"]
    assert any("request body" in message for message in verbose_messages)
    assert any(user_prompt in message for message in verbose_messages)
    assert not any("[omitted" in message for message in verbose_messages if "request body" in message)


def test_openai_provider_reports_invalid_json_with_context(monkeypatch) -> None:
    provider = OpenAIProvider(model="gpt-5-nano", api_key="test-key")
    invalid_content = '{"topic_updates": [], "should_continue": false "rationale": "broken"}'
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **kwargs: SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content=invalid_content))]
                )
            )
        )
    )
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

    with pytest.raises(ValueError) as exc_info:
        provider.digest_batch(
            DigestBatchRequest(
                config=DigestConfig(),
                batch_number=1,
                total_batches=1,
                chunk_batch=[],
                current_topics=[],
            )
        )

    message = str(exc_info.value)
    assert "OpenAI model gpt-5-nano returned invalid JSON in the model response" in message
    assert "Expecting ',' delimiter" in message
    assert "Received 69 chars." in message
    assert '<<<HERE>>>"<<<HERE>>>rationale' in message


def test_ollama_provider_reports_invalid_model_json_with_context(monkeypatch) -> None:
    provider = OllamaProvider(model="llama3.1")
    invalid_content = '{"topic_updates": [], "should_continue": false "rationale": "broken"}'

    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"message": {"content": self.content}}).encode("utf-8")

    responses = iter([invalid_content, invalid_content])

    monkeypatch.setattr(
        "digester.providers.ollama_provider.urlopen",
        lambda request: FakeResponse(next(responses)),
    )

    with pytest.raises(ValueError) as exc_info:
        provider.digest_batch(
            DigestBatchRequest(
                config=DigestConfig(),
                batch_number=1,
                total_batches=1,
                chunk_batch=[],
                current_topics=[],
            )
        )

    message = str(exc_info.value)
    assert "Ollama model llama3.1 returned invalid JSON in the model response" in message
    assert "Expecting ',' delimiter" in message
    assert "Received 69 chars." in message
    assert '<<<HERE>>>"<<<HERE>>>rationale' in message


def test_ollama_provider_reports_invalid_http_body_with_context(monkeypatch) -> None:
    provider = OllamaProvider(model="llama3.1")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return b'{"message": {"content": "oops"}'

    monkeypatch.setattr("digester.providers.ollama_provider.urlopen", lambda request: FakeResponse())

    with pytest.raises(ValueError) as exc_info:
        provider.digest_batch(
            DigestBatchRequest(
                config=DigestConfig(),
                batch_number=1,
                total_batches=1,
                chunk_batch=[],
                current_topics=[],
            )
        )

    message = str(exc_info.value)
    assert "Ollama model llama3.1 returned invalid JSON in the HTTP response body" in message
    assert "Expecting ',' delimiter" in message
    assert "Try a smaller batch or a model with stronger JSON adherence." not in message


def test_ollama_provider_reports_truncated_model_json_with_guidance(monkeypatch) -> None:
    provider = OllamaProvider(model="llama3.1")
    invalid_content = '{"topic_updates": [], "should_continue": false, "rationale": "cut off"'

    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"message": {"content": self.content}}).encode("utf-8")

    responses = iter([invalid_content, invalid_content])
    monkeypatch.setattr(
        "digester.providers.ollama_provider.urlopen",
        lambda request: FakeResponse(next(responses)),
    )

    with pytest.raises(ValueError) as exc_info:
        provider.digest_batch(
            DigestBatchRequest(
                config=DigestConfig(),
                batch_number=1,
                total_batches=1,
                chunk_batch=[],
                current_topics=[],
            )
        )

    message = str(exc_info.value)
    assert "Ollama model llama3.1 returned invalid JSON in the model response" in message
    assert "The model response appears truncated before the JSON finished." in message
    assert '<<<HERE>>><EOF><<<HERE>>>' in message


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
