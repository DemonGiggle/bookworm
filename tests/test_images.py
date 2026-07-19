import json
from types import SimpleNamespace
from urllib.error import URLError

import pytest

from digester.images import (
    MockImageAnalyzer,
    OllamaImageAnalyzer,
    OpenAIImageAnalyzer,
    create_image_analyzer,
)
from digester.images.factory import ImageAnalyzerSettings
from digester.core.models import EmbeddedImage, SourceRef


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


def test_create_image_analyzer_builds_mock_image_analyzer() -> None:
    analyzer = create_image_analyzer(
        ImageAnalyzerSettings(
            analyzer_kind="mock-image",
            model="fake-vision",
        )
    )

    assert isinstance(analyzer, MockImageAnalyzer)
    assert analyzer.model == "fake-vision"


def test_create_image_analyzer_builds_ollama_image_analyzer() -> None:
    analyzer = create_image_analyzer(
        ImageAnalyzerSettings(
            analyzer_kind="ollama",
            model="gemma3:4b",
            ollama_host="192.168.1.20",
            ollama_port=11435,
            timeout_seconds=30,
        )
    )

    assert isinstance(analyzer, OllamaImageAnalyzer)
    assert analyzer.model == "gemma3:4b"
    assert analyzer.base_url == "http://192.168.1.20:11435"
    assert analyzer.timeout_seconds == 30


def test_create_image_analyzer_passes_temperature() -> None:
    analyzer = create_image_analyzer(
        ImageAnalyzerSettings(
            analyzer_kind="ollama",
            model="gemma3:4b",
            temperature=0.25,
        )
    )

    assert isinstance(analyzer, OllamaImageAnalyzer)
    assert analyzer.temperature == 0.25


def test_create_image_analyzer_builds_opencode_go_analyzer() -> None:
    analyzer = create_image_analyzer(
        ImageAnalyzerSettings(
            analyzer_kind="opencode-go",
            model="opencode-go/kimi-k2.6",
            api_key="go-key",
        )
    )

    assert isinstance(analyzer, OpenAIImageAnalyzer)
    assert analyzer.model == "kimi-k2.6"
    assert analyzer._client_provider.base_url == "https://opencode.ai/zen/go/v1"
    assert analyzer._client_provider.api_key == "go-key"
    assert analyzer.validate_model is False


def test_compatible_image_analyzers_skip_native_model_retrieve(monkeypatch) -> None:
    for analyzer_kind, base_url in (
        ("openai-compatible", "https://compatible.example/v1"),
        ("opencode-go", None),
    ):
        analyzer = create_image_analyzer(
            ImageAnalyzerSettings(
                analyzer_kind=analyzer_kind,
                model="kimi-k2.6",
                api_key="test-key",
                base_url=base_url,
            )
        )
        called = []
        monkeypatch.setattr(
            analyzer._client_provider,
            "validate_configuration",
            lambda: called.append(True),
        )

        analyzer.validate_configuration()

        assert called == []


def test_native_openai_image_analyzer_keeps_model_validation(monkeypatch) -> None:
    analyzer = create_image_analyzer(
        ImageAnalyzerSettings(
            analyzer_kind="openai",
            model="gpt-4.1-mini",
            api_key="test-key",
        )
    )
    called = []
    monkeypatch.setattr(
        analyzer._client_provider,
        "validate_configuration",
        lambda: called.append(True),
    )

    analyzer.validate_configuration()

    assert called == [True]


def test_opencode_go_image_analyzer_sends_multimodal_chat_request(monkeypatch) -> None:
    analyzer = create_image_analyzer(
        ImageAnalyzerSettings(
            analyzer_kind="opencode-go",
            model="kimi-k2.6",
            api_key="go-key",
        )
    )
    captured = {}

    def fake_create(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=json.dumps(
                            {"summary": "A red square is visible.", "key_points": ["Red"]}
                        )
                    )
                )
            ]
        )

    fake_client = SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=fake_create))
    )
    monkeypatch.setattr(analyzer._client_provider, "_client", lambda: fake_client)

    result = analyzer.analyze(
        EmbeddedImage(
            image_id="red-square",
            source_ref=SourceRef("fixture", "/tmp/red.png", "image 1"),
            filename="red.png",
            mime_type="image/png",
            data=b"png-bytes",
        )
    )

    assert captured["model"] == "kimi-k2.6"
    image_part = captured["messages"][1]["content"][1]
    assert image_part["type"] == "image_url"
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")
    assert result.summary == "A red square is visible."


def test_mock_image_analyzer_preserves_caption_and_context() -> None:
    analyzer = MockImageAnalyzer(model="fake-vision")

    result = analyzer.analyze(
        EmbeddedImage(
            image_id="guide-image-1",
            source_ref=SourceRef(
                source_id="guide",
                source_path="/tmp/guide.docx",
                locator="embedded image 1 near paragraph 2",
            ),
            filename="image1.png",
            mime_type="image/png",
            data=b"image-bytes",
            caption="Screenshot shows the confirmation dialog",
            context_text="Previous step opens the setup wizard.",
        )
    )

    assert "Screenshot shows the confirmation dialog" in result.summary
    assert "Nearby document context: Previous step opens the setup wizard." in result.key_points


def test_ollama_image_analyzer_sends_base64_image_and_parses_analysis(monkeypatch) -> None:
    analyzer = OllamaImageAnalyzer(model="gemma3:4b", timeout_seconds=45)
    captured = {}

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
                                "summary": "The screenshot shows a confirmation dialog.",
                                "key_points": ["The highlighted button is Continue."],
                            }
                        )
                    }
                }
            ).encode("utf-8")

    def fake_urlopen(request, timeout=None):
        captured["url"] = request.full_url
        captured["timeout"] = timeout
        captured["payload"] = json.loads(request.data.decode("utf-8"))
        return FakeResponse()

    monkeypatch.setattr("digester.images.ollama_image_analyzer.urlopen", fake_urlopen)
    result = analyzer.analyze(
        EmbeddedImage(
            image_id="guide-image-1",
            source_ref=SourceRef(
                source_id="guide",
                source_path="/tmp/guide.docx",
                locator="embedded image 1 near paragraph 2",
            ),
            filename="image1.png",
            mime_type="image/png",
            data=b"image-bytes",
            caption="Screenshot shows the confirmation dialog",
            context_text="Previous step opens the setup wizard.",
        )
    )

    assert captured["url"] == "http://127.0.0.1:11434/api/chat"
    assert captured["timeout"] == 45
    assert captured["payload"]["model"] == "gemma3:4b"
    assert captured["payload"]["stream"] is False
    assert captured["payload"]["format"] == "json"
    assert captured["payload"]["options"]["temperature"] == 0.0
    assert captured["payload"]["messages"][1]["images"] == ["aW1hZ2UtYnl0ZXM="]
    assert result.summary == "The screenshot shows a confirmation dialog."
    assert result.key_points == ["The highlighted button is Continue."]


def test_ollama_image_analyzer_verbose_logging_includes_model_response(monkeypatch) -> None:
    analyzer = OllamaImageAnalyzer(model="gemma3:4b")
    reporter = RecordingVerboseReporter()
    analyzer.set_progress_reporter(reporter)
    response_content = json.dumps(
        {
            "summary": "The image shows a setup wizard confirmation dialog.",
            "key_points": ["The Continue button is highlighted."],
        }
    )

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self) -> bytes:
            return json.dumps({"message": {"content": response_content}}).encode("utf-8")

    monkeypatch.setattr("digester.images.ollama_image_analyzer.urlopen", lambda request: FakeResponse())
    analyzer.analyze(
        EmbeddedImage(
            image_id="guide-image-1",
            source_ref=SourceRef(
                source_id="guide",
                source_path="/tmp/guide.docx",
                locator="embedded image 1 near paragraph 2",
            ),
            filename="image1.png",
            mime_type="image/png",
            data=b"image-bytes",
            caption="Screenshot shows the confirmation dialog",
        )
    )

    verbose_messages = [message for kind, message in reporter.messages if kind == "verbose"]
    assert any("request preview" in message and "--- system ---" in message for message in verbose_messages)
    assert any(
        "attaching image payload" in message
        and "embedded image 1 near paragraph 2" in message
        and "bytes=11" in message
        and "base64_chars=16" in message
        for message in verbose_messages
    )
    assert any("response preview" in message and "setup wizard confirmation dialog" in message for message in verbose_messages)


def test_ollama_image_analyzer_reports_connection_failure(monkeypatch) -> None:
    analyzer = OllamaImageAnalyzer(model="gemma3:4b", host="192.168.1.20")
    monkeypatch.setattr(
        "digester.images.ollama_image_analyzer.urlopen",
        lambda request: (_ for _ in ()).throw(URLError("connection refused")),
    )

    with pytest.raises(ValueError, match="Unable to reach Ollama image analyzer"):
        analyzer.analyze(
            EmbeddedImage(
                image_id="guide-image-1",
                source_ref=SourceRef(
                    source_id="guide",
                    source_path="/tmp/guide.docx",
                    locator="embedded image 1 near paragraph 2",
                ),
                filename="image1.png",
                mime_type="image/png",
                data=b"image-bytes",
            )
        )
