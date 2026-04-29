import json
from urllib.error import URLError

import pytest

from digester.images import MockImageAnalyzer, OllamaImageAnalyzer, create_image_analyzer
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
