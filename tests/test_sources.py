from pathlib import Path

from docx import Document
from openpyxl import Workbook

from digester.sources.registry import SourceRegistry


def test_registry_loads_plain_text(tmp_path: Path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("alpha\n\nbeta", encoding="utf-8")

    documents = SourceRegistry().load_paths([path])

    assert len(documents) == 1
    assert documents[0].sections[0].content == "alpha\n\nbeta"


def test_registry_loads_docx(tmp_path: Path) -> None:
    path = tmp_path / "memo.docx"
    document = Document()
    document.add_paragraph("First paragraph")
    document.add_paragraph("Second paragraph")
    document.save(path)

    documents = SourceRegistry().load_paths([path])

    assert documents[0].sections[0].content == "First paragraph\n\nSecond paragraph"


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
