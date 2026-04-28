from digester.images import MockImageAnalyzer, create_image_analyzer
from digester.images.factory import ImageAnalyzerSettings
from digester.core.models import EmbeddedImage, SourceRef


def test_create_image_analyzer_builds_mock_image_analyzer() -> None:
    analyzer = create_image_analyzer(
        ImageAnalyzerSettings(
            analyzer_kind="mock-image",
            model="fake-vision",
        )
    )

    assert isinstance(analyzer, MockImageAnalyzer)
    assert analyzer.model == "fake-vision"


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
