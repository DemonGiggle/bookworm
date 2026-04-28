from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from openpyxl import load_workbook

from ..core.models import DocumentSection, SourceDocument, SourceRef
from ..images.base import ImageAnalyzer
from .base import SourceAdapter


def _render_row(row: List[object]) -> str:
    return " | ".join("" if cell is None else str(cell) for cell in row).strip()


class SpreadsheetAdapter(SourceAdapter):
    supported_suffixes = (".xlsx", ".xlsm")
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def load(
        self,
        path: Path,
        image_analyzer: Optional[ImageAnalyzer] = None,
    ) -> SourceDocument:
        workbook = load_workbook(filename=str(path), data_only=True, read_only=True)
        source_id = path.stem.replace(" ", "-").lower()
        sections = []
        for sheet in workbook.worksheets:
            rows = []
            for row in sheet.iter_rows(values_only=True):
                rendered = _render_row(list(row))
                if rendered:
                    rows.append(rendered)
            sections.append(
                DocumentSection(
                    heading=sheet.title,
                    content="\n".join(rows),
                    source_ref=SourceRef(
                        source_id=source_id,
                        source_path=str(path),
                        locator="sheet {title}".format(title=sheet.title),
                    ),
                )
            )
        return SourceDocument(
            source_id=source_id,
            path=path,
            media_type=self.media_type,
            title=path.stem,
            sections=sections,
        )
