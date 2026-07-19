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
from digester.providers import MockLLMProvider, OpenCodeGoProvider, ProviderSettings, create_provider
from digester.providers.opencode_go_provider import OPENCODE_GO_BASE_URL
from digester.providers.ollama_provider import OllamaProvider, _normalize_base_url
from digester.providers.openai_compatible import OpenAICompatibleProvider
from digester.providers.openai_provider import OpenAIProvider
from digester.providers.parsing import parse_digest_decision, parse_finalized_topics
from digester.providers.schemas import (
    DIGEST_RESPONSE_SCHEMA,
    FINALIZE_RESPONSE_SCHEMA,
    schema_with_allowed_chunk_ids,
    validate_payload,
)


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


def _valid_digest_payload():
    return {
        "topic_updates": [],
        "should_continue": False,
        "rationale": "Done.",
    }


def _valid_finalized_payload():
    return {
        "topics": [
            {
                "slug": "overview",
                "title": "Overview",
                "routing_description": "Use this skill when reviewing the overview.",
                "summary": "A complete overview summary.",
                "key_points": ["Check the source."],
                "workflow_notes": ["Validate before reuse."],
                                    "reference_chunk_ids": ["source-chunk-1"],
            }
        ]
    }


@pytest.mark.parametrize(
    ("mutate", "expected_path"),
    [
        (lambda payload: payload.pop("rationale"), "<root>"),
        (lambda payload: payload.update(should_continue="false"), "should_continue"),
        (lambda payload: payload.update(extra="unexpected"), "<root>"),
    ],
)
def test_digest_schema_rejects_missing_wrong_and_extra_fields(mutate, expected_path) -> None:
    payload = _valid_digest_payload()
    mutate(payload)

    with pytest.raises(ValueError, match="failed JSON Schema validation") as exc_info:
        validate_payload(payload, DIGEST_RESPONSE_SCHEMA, "bookworm_digest_response")

    assert expected_path in str(exc_info.value)


def test_finalize_schema_rejects_wrong_list_item_type() -> None:
    payload = _valid_finalized_payload()
    payload["topics"][0]["key_points"] = ["valid", 42]

    with pytest.raises(ValueError, match="topics.0.key_points.1"):
        validate_payload(payload, FINALIZE_RESPONSE_SCHEMA, "bookworm_finalize_response")


def test_digest_decision_rejects_string_boolean() -> None:
    payload = _valid_digest_payload()
    payload["should_continue"] = "false"

    with pytest.raises(ValueError, match="must be a JSON boolean"):
        DigestDecision.from_payload(payload, chunk_refs={})


def test_digest_references_resolve_and_dedupe_chunk_ids() -> None:
    ref = SourceRef(
        source_id="source",
        source_path="/tmp/source.txt",
        locator="section 1",
    )
    payload = _valid_digest_payload()
    payload["topic_updates"] = [
        {
            "slug": "overview",
            "title": "Overview",
            "routing_description": "Use this skill when reviewing the overview.",
            "summary": "Summary grounded in a chunk.",
            "key_points": ["Check the evidence."],
            "workflow_notes": ["Validate before reuse."],
            "reference_chunk_ids": ["chunk-1", "chunk-1"],
        }
    ]

    decision = parse_digest_decision(payload, chunk_refs={"chunk-1": ref})

    assert decision.topic_updates[0].evidence_chunk_ids == ["chunk-1"]
    assert decision.topic_updates[0].references == [ref]
    assert decision.topic_updates[0].evidence_refs == {"chunk-1": ref}


@pytest.mark.parametrize("chunk_id", ["unknown-chunk", "previous-batch-chunk"])
def test_digest_rejects_unknown_or_cross_batch_chunk_ids(chunk_id) -> None:
    payload = _valid_digest_payload()
    payload["topic_updates"] = [
        {
            "slug": "overview",
            "title": "Overview",
            "routing_description": "Use this skill when reviewing the overview.",
            "summary": "Summary with invalid provenance.",
            "key_points": [],
            "workflow_notes": [],
            "reference_chunk_ids": [chunk_id],
        }
    ]

    with pytest.raises(ValueError, match="unknown chunk IDs"):
        parse_digest_decision(payload, chunk_refs={})


def test_digest_missing_evidence_does_not_attach_batch_fallbacks() -> None:
    unrelated_ref = SourceRef(
        source_id="source",
        source_path="/tmp/source.txt",
        locator="section 1",
    )
    payload = _valid_digest_payload()
    payload["topic_updates"] = [
        {
            "slug": "overview",
            "title": "Overview",
            "routing_description": "Use this skill when reviewing the overview.",
            "summary": "Summary without supplied evidence.",
            "key_points": [],
            "workflow_notes": [],
            "reference_chunk_ids": [],
        }
    ]

    decision = parse_digest_decision(payload, chunk_refs={"chunk-1": unrelated_ref})

    assert decision.topic_updates[0].references == []
    assert decision.topic_updates[0].evidence_chunk_ids == []


def test_topic_merge_preserves_multi_batch_evidence() -> None:
    first_ref = SourceRef("source", "/tmp/source.txt", "section 1")
    second_ref = SourceRef("source", "/tmp/source.txt", "section 2")
    topic = TopicDigest(
        slug="overview",
        title="Overview",
        summary="First batch.",
        references=[first_ref],
        evidence_chunk_ids=["chunk-1"],
        evidence_refs={"chunk-1": first_ref},
    )

    topic.merge(
        TopicDigest(
            slug="overview",
            title="Overview",
            summary="Second batch.",
            references=[second_ref],
            evidence_chunk_ids=["chunk-2"],
            evidence_refs={"chunk-2": second_ref},
        )
    )

    assert topic.evidence_chunk_ids == ["chunk-1", "chunk-2"]
    assert topic.references == [first_ref, second_ref]
    assert topic.evidence_refs == {"chunk-1": first_ref, "chunk-2": second_ref}


def test_openai_retries_schema_validation_failure_and_uses_native_schema(monkeypatch) -> None:
    provider = OpenAIProvider(model="gpt-5-nano", api_key="test-key")
    invalid_payload = _valid_digest_payload()
    invalid_payload["should_continue"] = "false"
    responses = iter([invalid_payload, _valid_digest_payload()])
    captured_calls = []

    def fake_create(**kwargs):
        captured_calls.append(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(next(responses)))
                )
            ]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

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
    assert len(captured_calls) == 2
    response_format = captured_calls[0]["response_format"]
    assert response_format["type"] == "json_schema"
    assert response_format["json_schema"]["strict"] is True
    assert response_format["json_schema"]["schema"] == schema_with_allowed_chunk_ids(
        DIGEST_RESPONSE_SCHEMA, "topic_updates", []
    )


def test_openai_retries_unknown_chunk_id_with_batch_scoped_schema(monkeypatch) -> None:
    provider = OpenAIProvider(model="gpt-5-nano", api_key="test-key")
    invalid_payload = _valid_digest_payload()
    invalid_payload["topic_updates"] = [
        {
            "slug": "overview",
            "title": "Overview",
            "routing_description": "Use this skill when reviewing the overview.",
            "summary": "A source-backed overview.",
            "key_points": [],
            "workflow_notes": [],
            "reference_chunk_ids": ["stale-chunk"],
        }
    ]
    valid_payload = json.loads(json.dumps(invalid_payload))
    valid_payload["topic_updates"][0]["reference_chunk_ids"] = ["chunk-1"]
    responses = iter([invalid_payload, valid_payload])
    call_count = 0

    def fake_create(**kwargs):
        nonlocal call_count
        call_count += 1
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content=json.dumps(next(responses)))
                )
            ]
        )

    monkeypatch.setattr(
        provider,
        "_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    ref = SourceRef("source", "/tmp/source.txt", "section 1")

    decision = provider.digest_batch(
        DigestBatchRequest(
            config=DigestConfig(),
            batch_number=1,
            total_batches=1,
            chunk_batch=[
                ContentChunk(
                    chunk_id="chunk-1",
                    source_id="source",
                    source_path="/tmp/source.txt",
                    section_heading="Overview",
                    text="Evidence",
                    source_ref=ref,
                )
            ],
            current_topics=[],
        )
    )

    assert call_count == 2
    assert decision.topic_updates[0].references == [ref]


def test_ollama_rejects_schema_invalid_retry_and_uses_native_schema(monkeypatch) -> None:
    provider = OllamaProvider(model="gemma")
    invalid_payload = _valid_digest_payload()
    invalid_payload["should_continue"] = "false"
    captured_requests = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps(
                {"message": {"content": json.dumps(invalid_payload)}}
            ).encode("utf-8")

    def fake_urlopen(request):
        captured_requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse()

    monkeypatch.setattr("digester.providers.ollama_provider.urlopen", fake_urlopen)

    with pytest.raises(ValueError, match="should_continue"):
        provider.digest_batch(
            DigestBatchRequest(
                config=DigestConfig(),
                batch_number=1,
                total_batches=1,
                chunk_batch=[],
                current_topics=[],
            )
        )

    assert len(captured_requests) == 2
    assert captured_requests[0]["format"] == schema_with_allowed_chunk_ids(
        DIGEST_RESPONSE_SCHEMA, "topic_updates", []
    )


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


def test_create_provider_passes_stage_specific_temperatures() -> None:
    provider = create_provider(
        ProviderSettings(
            provider_kind="openai-compatible",
            model="local-model",
            api_key="test-key",
            base_url="http://127.0.0.1:9000/v1",
            digest_temperature=0.55,
            finalize_temperature=0.15,
            finalize_max_output_tokens=9000,
        )
    )

    assert isinstance(provider, OpenAIProvider)
    assert provider.digest_temperature == 0.55
    assert provider.finalize_temperature == 0.15
    assert provider.finalize_max_output_tokens == 9000


def test_create_provider_builds_opencode_go_provider_and_normalizes_model() -> None:
    provider = create_provider(
        ProviderSettings(
            provider_kind="opencode-go",
            model="opencode-go/kimi-k3",
            api_key="go-key",
            digest_temperature=0.2,
            finalize_temperature=0.0,
            finalize_max_output_tokens=8192,
            finalize_review_model="grok-4.5",
        )
    )

    assert isinstance(provider, OpenCodeGoProvider)
    assert provider.model == "kimi-k3"
    assert provider.base_url == OPENCODE_GO_BASE_URL
    assert provider.digest_temperature == 0.2
    assert provider.finalize_temperature == 0.0
    assert provider.finalize_max_output_tokens == 8192
    assert provider.finalize_review_passes == 1
    assert provider.finalize_review_model == "grok-4.5"


def test_opencode_go_uses_strict_json_schema_output() -> None:
    provider = OpenCodeGoProvider(model="kimi-k2.6", api_key="go-key")
    schema = {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
        "required": ["ok"],
        "additionalProperties": False,
    }

    response_format = provider._response_format(schema, "probe")

    assert response_format == {
        "type": "json_schema",
        "json_schema": {
            "name": "probe",
            "strict": True,
            "schema": schema,
        },
    }


def test_opencode_go_uses_distinct_model_for_grounding_review(monkeypatch) -> None:
    provider = OpenCodeGoProvider(
        model="kimi-k2.6",
        api_key="go-key",
        finalize_review_model="grok-4.5",
    )
    request_models = []

    def fake_complete_json(**kwargs):
        request_models.append(kwargs.get("request_model"))
        return {
            "topics": [
                {
                    "slug": "overview",
                    "title": "Overview",
                    "routing_description": "Use this skill when reviewing grounded guidance.",
                    "summary": "Grounded summary.",
                    "key_points": ["Grounded point."],
                    "workflow_notes": ["Grounded note."],
                    "reference_chunk_ids": ["source-chunk-1"],
                }
            ]
        }

    monkeypatch.setattr(provider, "_complete_json", fake_complete_json)
    source_ref = SourceRef(
        source_id="source",
        source_path="/tmp/source.txt",
        locator="full-document",
    )
    provider.finalize_topics(
        [
            TopicDigest(
                slug="overview",
                title="Overview",
                routing_description="Use this skill when reviewing draft guidance.",
                summary="Draft summary.",
                key_points=["Draft point."],
                references=[source_ref],
                evidence_chunk_ids=["source-chunk-1"],
                evidence_refs={"source-chunk-1": source_ref},
                evidence_texts={"source-chunk-1": "Grounded source text."},
            )
        ]
    )

    assert request_models == [None, "grok-4.5"]
    assert provider.finalize_reasoning_effort == "none"


def test_non_kimi_opencode_go_does_not_force_reasoning_effort() -> None:
    provider = OpenCodeGoProvider(model="deepseek-v4-pro", api_key="go-key")

    assert provider.finalize_reasoning_effort is None


def test_kimi_reasoning_effort_is_limited_only_for_finalization(monkeypatch) -> None:
    provider = OpenCodeGoProvider(model="kimi-k2.6", api_key="go-key")
    captured_calls = []

    def fake_create(**kwargs):
        captured_calls.append(kwargs)
        payload = (
            {"topic_updates": [], "should_continue": False, "rationale": "Done."}
            if len(captured_calls) == 1
            else {
                "topics": [
                    {
                        "slug": "overview",
                        "title": "Overview",
                        "routing_description": "Use this skill when reviewing grounded guidance.",
                        "summary": "A grounded final summary with actionable implementation detail.",
                        "key_points": ["Follow the documented sequence."],
                        "workflow_notes": ["Validate the result against source evidence."],
                        "reference_chunk_ids": ["source-chunk-1"],
                    }
                ]
            }
        )
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop",
                    message=SimpleNamespace(content=json.dumps(payload)),
                )
            ]
        )

    monkeypatch.setattr(
        provider,
        "_client",
        lambda: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
        ),
    )
    provider.digest_batch(
        DigestBatchRequest(
            config=DigestConfig(),
            batch_number=1,
            total_batches=1,
            chunk_batch=[],
            current_topics=[],
        )
    )
    provider.finalize_topics(
        [
            TopicDigest(
                slug="overview",
                title="Overview",
                routing_description="Use this skill when reviewing grounded guidance.",
                summary="A grounded draft summary.",
                key_points=["Follow the documented sequence."],
                workflow_notes=["Validate against the source."],
                references=[SourceRef("source", "/tmp/source.txt", "section 1")],
                evidence_chunk_ids=["source-chunk-1"],
                evidence_refs={
                    "source-chunk-1": SourceRef(
                        "source", "/tmp/source.txt", "section 1"
                    )
                },
                evidence_texts={"source-chunk-1": "Grounded evidence."},
            )
        ]
    )

    assert "reasoning_effort" not in captured_calls[0]
    assert captured_calls[1]["reasoning_effort"] == "none"


def test_generic_openai_compatible_keeps_json_object_output() -> None:
    provider = OpenAICompatibleProvider(
        model="compatible-model",
        api_key="test-key",
        base_url="https://compatible.example/v1",
    )

    assert provider._response_format({"type": "object"}, "probe") == {
        "type": "json_object"
    }


@pytest.mark.parametrize("model", ["Qwen3.7-Plus", "opencode-go/MiniMax-M3"])
def test_opencode_go_rejects_messages_only_models(model) -> None:
    with pytest.raises(ValueError, match="uses the /messages API"):
        create_provider(
            ProviderSettings(
                provider_kind="opencode-go",
                model=model,
                api_key="go-key",
            )
        )


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
                                            "reference_chunk_ids": [],
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


def test_ollama_provider_uses_stage_specific_temperatures(monkeypatch) -> None:
    provider = OllamaProvider(
        model="llama3.1",
        digest_temperature=0.45,
        finalize_temperature=0.05,
    )
    captured_payloads = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            payload = (
                {
                    "topic_updates": [],
                    "should_continue": False,
                    "rationale": "Enough evidence collected.",
                }
                if len(captured_payloads) == 1
                else {
                    "topics": [
                        {
                            "slug": "overview",
                            "title": "Overview",
                            "routing_description": "Use this skill when reviewing the finalized overview guidance.",
                            "summary": "Summary.",
                            "key_points": ["Point"],
                            "workflow_notes": ["Note"],
                            "reference_chunk_ids": ["source-chunk-1"],
                        }
                    ]
                }
            )
            return json.dumps({"message": {"content": json.dumps(payload)}}).encode("utf-8")

    def fake_urlopen(request):
        captured_payloads.append(json.loads(request.data.decode("utf-8")))
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
    provider.finalize_topics(
        [
            TopicDigest(
                slug="overview",
                title="Overview",
                routing_description="Use this skill when reviewing the finalized overview guidance.",
                summary="Summary.",
                key_points=["Point"],
                workflow_notes=["Note"],
                references=[SourceRef("source", "/tmp/source.txt", "section 1")],
                evidence_chunk_ids=["source-chunk-1"],
                evidence_refs={
                    "source-chunk-1": SourceRef(
                        "source", "/tmp/source.txt", "section 1"
                    )
                },
                evidence_texts={"source-chunk-1": "Grounded evidence."},
            )
        ]
    )

    assert captured_payloads[0]["options"]["temperature"] == 0.45
    assert captured_payloads[1]["options"]["temperature"] == 0.05
    assert captured_payloads[1]["options"]["num_predict"] == 4096


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
                    references=[
                        SourceRef(
                            source_id="source",
                            source_path="/tmp/source.txt",
                            locator="full-document",
                        )
                    ],
                        evidence_chunk_ids=["source-chunk-1"],
                        evidence_refs={
                            "source-chunk-1": SourceRef(
                                source_id="source",
                                source_path="/tmp/source.txt",
                                locator="full-document",
                            )
                        },
                        evidence_texts={"source-chunk-1": "Grounded evidence."},
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
                    "reference_chunk_ids": ["source-chunk-1"],
                }
            ],
            "should_continue": False,
            "rationale": "Done.",
        },
            chunk_refs={
                "source-chunk-1": SourceRef(
                    source_id="source",
                    source_path="/tmp/source.txt",
                    locator="full-document",
                )
            },
    )

    assert decision.topic_updates[0].key_points == ["check"]
    assert decision.topic_updates[0].workflow_notes == [
        "Validate the generated guidance before editing."
    ]


def test_parse_finalized_topics_resolves_chunk_ids_from_fallback_topic() -> None:
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
                    "reference_chunk_ids": ["source-chunk-1"],
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
                evidence_chunk_ids=["source-chunk-1"],
                evidence_refs={"source-chunk-1": fallback_ref},
            )
        ],
    )

    assert parsed[0].references == [fallback_ref]


def test_parse_finalized_topics_preserves_all_accumulated_evidence() -> None:
    first_ref = SourceRef(
        source_id="source",
        source_path="/tmp/source.pdf",
        locator="page 1",
    )
    second_ref = SourceRef(
        source_id="source",
        source_path="/tmp/source.pdf",
        locator="page 2",
    )
    fallback = TopicDigest(
        slug="overview",
        title="Overview",
        routing_description="Use this skill when reviewing the draft overview guidance.",
        summary="Draft facts grounded across both pages.",
        key_points=[],
        references=[first_ref, second_ref],
        evidence_chunk_ids=["source-chunk-1", "source-chunk-2"],
        evidence_refs={
            "source-chunk-1": first_ref,
            "source-chunk-2": second_ref,
        },
        evidence_texts={
            "source-chunk-1": "First grounded fact.",
            "source-chunk-2": "Second grounded fact.",
        },
    )

    parsed = parse_finalized_topics(
        {
            "topics": [
                {
                    "slug": "overview",
                    "title": "Overview",
                    "routing_description": "Use this skill when reviewing the overview guidance.",
                    "summary": "Retains facts grounded across both pages.",
                    "key_points": ["Keep both grounded facts."],
                    "workflow_notes": ["Verify the cited source pages."],
                    "reference_chunk_ids": ["source-chunk-1"],
                }
            ]
        },
        fallback_topics=[fallback],
    )

    assert parsed[0].evidence_chunk_ids == ["source-chunk-1", "source-chunk-2"]
    assert parsed[0].references == [first_ref, second_ref]
    assert parsed[0].evidence_refs == fallback.evidence_refs
    assert parsed[0].evidence_texts == fallback.evidence_texts


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


def test_openai_provider_uses_stage_specific_temperatures(monkeypatch) -> None:
    provider = OpenAIProvider(
        model="gpt-5-nano",
        api_key="test-key",
        digest_temperature=0.5,
        finalize_temperature=0.2,
    )
    captured_calls = []

    def fake_create(**kwargs):
        captured_calls.append(kwargs)
        payload = (
            {
                "topic_updates": [],
                "should_continue": False,
                "rationale": "Enough context collected.",
            }
            if len(captured_calls) == 1
            else {
                "topics": [
                    {
                        "slug": "overview",
                        "title": "Overview",
                        "routing_description": "Use this skill when reviewing finalized guidance.",
                        "summary": "Summary.",
                        "key_points": ["Point"],
                        "workflow_notes": ["Note"],
                        "reference_chunk_ids": ["source-chunk-1"],
                    }
                ]
            }
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload)))]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        )
    )
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

    provider.digest_batch(
        DigestBatchRequest(
            config=DigestConfig(),
            batch_number=1,
            total_batches=1,
            chunk_batch=[],
            current_topics=[],
        )
    )
    provider.finalize_topics(
        [
            TopicDigest(
                slug="overview",
                title="Overview",
                routing_description="Use this skill when reviewing finalized guidance.",
                summary="Summary.",
                key_points=["Point"],
                workflow_notes=["Note"],
                references=[SourceRef("source", "/tmp/source.txt", "section 1")],
                evidence_chunk_ids=["source-chunk-1"],
                evidence_refs={
                    "source-chunk-1": SourceRef(
                        "source", "/tmp/source.txt", "section 1"
                    )
                },
                evidence_texts={"source-chunk-1": "Grounded evidence."},
            )
        ]
    )

    assert captured_calls[0]["temperature"] == 0.5
    assert captured_calls[1]["temperature"] == 0.2
    assert captured_calls[1]["max_completion_tokens"] == 4096


def test_openai_provider_empty_response_reports_token_limit_metadata(monkeypatch) -> None:
    provider = OpenAIProvider(model="gpt-5-nano", api_key="test-key")
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content=""),
            )
        ],
        usage=SimpleNamespace(
            completion_tokens=4096,
            completion_tokens_details=SimpleNamespace(reasoning_tokens=4096),
        ),
    )
    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **kwargs: response)
        )
    )
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

    with pytest.raises(ValueError) as exc_info:
        provider._request_json_completion(
            system_prompt="system",
            user_prompt="user",
            temperature=0.0,
            response_schema={"type": "object"},
            schema_name="test",
            max_output_tokens=4096,
        )

    message = str(exc_info.value)
    assert "finish_reason=length" in message
    assert "completion_tokens=4096" in message
    assert "reasoning_tokens=4096" in message
    assert "Increase the finalization output-token budget" in message


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


def test_openai_provider_retries_invalid_json_with_schema_example(monkeypatch) -> None:
    provider = OpenAIProvider(model="gpt-5-nano", api_key="test-key")
    reporter = RecordingVerboseReporter()
    provider.set_progress_reporter(reporter)
    invalid_content = '{"topic_updates": [], "should_continue": false "rationale": "broken"}'
    valid_content = json.dumps(
        {
            "topic_updates": [],
            "should_continue": False,
            "rationale": "Recovered on retry.",
        }
    )
    captured_calls = []

    def fake_create(**kwargs):
        captured_calls.append(kwargs)
        content = invalid_content if len(captured_calls) == 1 else valid_content
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=fake_create)
        )
    )
    monkeypatch.setattr(provider, "_client", lambda: fake_client)

    decision = provider.digest_batch(
        DigestBatchRequest(
            config=DigestConfig(),
            batch_number=1,
            total_batches=1,
            chunk_batch=[],
            current_topics=[],
        )
    )

    verbose_messages = [message for kind, message in reporter.messages if kind == "verbose"]
    assert decision.rationale == "Recovered on retry."
    assert len(captured_calls) == 2
    retry_system_prompt = captured_calls[1]["messages"][0]["content"]
    assert "Follow this exact JSON shape example:" in retry_system_prompt
    assert '"topic_updates":[{' in retry_system_prompt
    assert any("retrying once with a stricter JSON-only instruction and a compact schema example" in message for message in verbose_messages)


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


def test_ollama_provider_retries_invalid_json_with_schema_example(monkeypatch) -> None:
    provider = OllamaProvider(model="llama3.1")
    reporter = RecordingVerboseReporter()
    provider.set_progress_reporter(reporter)
    invalid_content = '{"topic_updates": [], "should_continue": false "rationale": "broken"}'
    valid_content = json.dumps(
        {
            "topic_updates": [],
            "should_continue": False,
            "rationale": "Recovered on retry.",
        }
    )
    captured_requests = []

    class FakeResponse:
        def __init__(self, content: str) -> None:
            self.content = content

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"message": {"content": self.content}}).encode("utf-8")

    responses = iter([invalid_content, valid_content])

    def fake_urlopen(request):
        captured_requests.append(json.loads(request.data.decode("utf-8")))
        return FakeResponse(next(responses))

    monkeypatch.setattr("digester.providers.ollama_provider.urlopen", fake_urlopen)

    decision = provider.digest_batch(
        DigestBatchRequest(
            config=DigestConfig(),
            batch_number=1,
            total_batches=1,
            chunk_batch=[],
            current_topics=[],
        )
    )

    verbose_messages = [message for kind, message in reporter.messages if kind == "verbose"]
    assert decision.rationale == "Recovered on retry."
    assert len(captured_requests) == 2
    retry_system_prompt = captured_requests[1]["messages"][0]["content"]
    assert "Follow this exact JSON shape example:" in retry_system_prompt
    assert '"topic_updates":[{' in retry_system_prompt
    assert any("retrying once with a stricter JSON-only instruction and a compact schema example" in message for message in verbose_messages)


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
