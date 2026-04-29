from base64 import b64decode
from pathlib import Path

from docx import Document
from openpyxl import Workbook

from digester.images import MockImageAnalyzer
from digester.images.base import ImageAnalyzer
from digester.core.models import EmbeddedImage
from digester.sources.registry import SourceRegistry


def _write_test_png(path: Path) -> None:
    path.write_bytes(
        b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jK4QAAAAASUVORK5CYII=")
    )


def _write_docx_with_embedded_image(path: Path) -> None:
    image_path = path.with_suffix(".png")
    _write_test_png(image_path)
    document = Document()
    document.add_paragraph("Before image")
    image_paragraph = document.add_paragraph("Screenshot shows the confirmation dialog")
    image_paragraph.add_run().add_picture(str(image_path))
    document.add_paragraph("After image")
    document.save(path)


def _write_docx_with_table_image(path: Path) -> None:
    image_path = path.with_suffix(".png")
    _write_test_png(image_path)
    document = Document()
    document.add_paragraph("Before table")
    table = document.add_table(rows=1, cols=1)
    image_paragraph = table.cell(0, 0).paragraphs[0]
    image_paragraph.text = "Screenshot in a table cell"
    image_paragraph.add_run().add_picture(str(image_path))
    document.add_paragraph("After table")
    document.save(path)


class RecordingReporter:
    def __init__(self) -> None:
        self.messages = []

    def update(self, message: str) -> None:
        self.messages.append(("update", message))

    def persist(self, message: str) -> None:
        self.messages.append(("persist", message))

    def verbose(self, message: str) -> None:
        self.messages.append(("verbose", message))

    def verbosity(self) -> int:
        return 0

    def clear(self) -> None:
        self.messages.append(("clear", ""))


def test_registry_loads_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("alpha\n\nbeta", encoding="utf-8")

    documents = SourceRegistry().load_paths([path])

    assert len(documents) == 1
    assert documents[0].sections[0].content == "alpha\n\nbeta"


def test_registry_recursively_loads_supported_files_from_directories(tmp_path: Path) -> None:
    nested_dir = tmp_path / "docs" / "guides"
    nested_dir.mkdir(parents=True)
    root_path = tmp_path / "docs" / "overview.txt"
    nested_path = nested_dir / "setup.md"
    root_path.write_text("root document", encoding="utf-8")
    nested_path.write_text("nested document", encoding="utf-8")

    documents = SourceRegistry().load_paths([tmp_path / "docs"])

    loaded_paths = {document.path for document in documents}
    assert loaded_paths == {root_path, nested_path}


def test_registry_loads_docx(tmp_path: Path) -> None:
    path = tmp_path / "memo.docx"
    document = Document()
    document.add_paragraph("First paragraph")
    document.add_paragraph("Second paragraph")
    document.save(path)

    documents = SourceRegistry().load_paths([path])

    assert documents[0].sections[0].content == "First paragraph\n\nSecond paragraph"


def test_registry_detects_docx_embedded_images_without_analyzer(tmp_path: Path) -> None:
    path = tmp_path / "with-image.docx"
    _write_docx_with_embedded_image(path)

    documents = SourceRegistry().load_paths([path])

    assert len(documents[0].sections) == 1
    assert len(documents[0].embedded_images) == 1
    assert documents[0].embedded_images[0].caption == "Screenshot shows the confirmation dialog"
    assert documents[0].embedded_images[0].source_ref.locator == "embedded image 1 near paragraph 2"
    assert documents[0].embedded_images[0].mime_type == "image/png"
    assert len(documents[0].embedded_images[0].data) > 0
    assert documents[0].extraction_notes == [
        (
            "Detected 1 embedded image(s): embedded image 1 near paragraph 2: "
            "file=image1.png, mime=image/png, bytes=68."
        )
    ]
    assert documents[0].extraction_warnings == [
        "Detected 1 embedded image(s) but no image analyzer is configured; image content was skipped."
    ]


def test_registry_loads_docx_embedded_images_with_analyzer(tmp_path: Path) -> None:
    path = tmp_path / "with-image.docx"
    _write_docx_with_embedded_image(path)

    documents = SourceRegistry().load_paths([path], image_analyzer=MockImageAnalyzer(model="fake-vision"))

    assert len(documents[0].sections) == 2
    image_section = documents[0].sections[1]
    assert image_section.heading == "Embedded image 1"
    assert image_section.content_kind == "image-analysis"
    assert image_section.source_ref.locator == "embedded image 1 near paragraph 2"
    assert "Visual summary:" in image_section.content
    assert "Screenshot shows the confirmation dialog" in image_section.content
    assert documents[0].extraction_notes == [
        (
            "Detected 1 embedded image(s): embedded image 1 near paragraph 2: "
            "file=image1.png, mime=image/png, bytes=68."
        ),
        (
            "Analyzing embedded image 1: embedded image 1 near paragraph 2: "
            "file=image1.png, mime=image/png, bytes=68."
        ),
        "Analyzed embedded image 1 successfully.",
    ]
    assert documents[0].extraction_warnings == []


def test_registry_detects_docx_embedded_images_inside_tables(tmp_path: Path) -> None:
    path = tmp_path / "with-table-image.docx"
    _write_docx_with_table_image(path)

    documents = SourceRegistry().load_paths([path], image_analyzer=MockImageAnalyzer(model="fake-vision"))

    assert len(documents[0].embedded_images) == 1
    assert documents[0].embedded_images[0].caption == "Screenshot in a table cell"
    assert documents[0].embedded_images[0].source_ref.locator == "embedded image 1 near table paragraph 1"
    assert documents[0].embedded_images[0].mime_type == "image/png"
    assert len(documents[0].embedded_images[0].data) > 0
    assert len(documents[0].sections) == 2
    image_section = documents[0].sections[1]
    assert image_section.content_kind == "image-analysis"
    assert "Screenshot in a table cell" in image_section.content
    assert documents[0].extraction_warnings == []


def test_registry_logs_docx_embedded_image_metadata(tmp_path: Path) -> None:
    path = tmp_path / "with-image.docx"
    _write_docx_with_embedded_image(path)
    reporter = RecordingReporter()

    SourceRegistry().load_paths([path], progress_reporter=reporter)

    persisted = [message for kind, message in reporter.messages if kind == "persist"]
    assert any(
        message.startswith("Note for with-image.docx: Detected 1 embedded image(s): ")
        and "embedded image 1 near paragraph 2" in message
        and "file=image1.png, mime=image/png, bytes=68" in message
        for message in persisted
    )
    assert any(
        message == (
            "Warning for with-image.docx: "
            "Detected 1 embedded image(s) but no image analyzer is configured; image content was skipped."
        )
        for message in persisted
    )


class FailingImageAnalyzer(ImageAnalyzer):
    def analyze(self, image: EmbeddedImage):
        raise ValueError("vision request timed out")


def test_registry_keeps_docx_text_when_embedded_image_analysis_fails(tmp_path: Path) -> None:
    path = tmp_path / "with-image.docx"
    _write_docx_with_embedded_image(path)

    documents = SourceRegistry().load_paths([path], image_analyzer=FailingImageAnalyzer())

    assert len(documents[0].sections) == 1
    assert documents[0].sections[0].content == (
        "Before image\n\nScreenshot shows the confirmation dialog\n\nAfter image"
    )
    assert documents[0].embedded_images[0].source_ref.locator == "embedded image 1 near paragraph 2"
    assert documents[0].extraction_notes == [
        (
            "Detected 1 embedded image(s): embedded image 1 near paragraph 2: "
            "file=image1.png, mime=image/png, bytes=68."
        ),
        (
            "Analyzing embedded image 1: embedded image 1 near paragraph 2: "
            "file=image1.png, mime=image/png, bytes=68."
        ),
    ]
    assert documents[0].extraction_warnings == [
        "Failed to analyze embedded image 1: vision request timed out"
    ]


def test_registry_loads_spreadsheet(tmp_path: Path) -> None:
    path = tmp_path / "sheet.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Summary"
    sheet.append(["Item", "Value"])
    sheet.append(["alpha", 3])
    workbook.save(path)

    documents = SourceRegistry().load_paths([path])

    assert "Item | Value" in documents[0].sections[0].content
    assert "alpha | 3" in documents[0].sections[0].content
