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
    assert documents[0].extraction_warnings == []


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
