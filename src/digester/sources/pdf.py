from __future__ import annotations

from pathlib import Path
from typing import Optional

from pypdf import PdfReader

from ..core.models import DocumentSection, SourceDocument, SourceRef
from ..images.base import ImageAnalyzer
from .base import SourceAdapter


class PdfAdapter(SourceAdapter):
    supported_suffixes = (".pdf",)
    media_type = "application/pdf"

    def load(
        self,
        path: Path,
        image_analyzer: Optional[ImageAnalyzer] = None,
    ) -> SourceDocument:
        reader = PdfReader(str(path))
        source_id = path.stem.replace(" ", "-").lower()
        sections = []
        warnings = []
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if not text:
                warnings.append("Page {page} did not yield extractable text.".format(page=index))
                continue
            sections.append(
                DocumentSection(
                    heading="Page {page}".format(page=index),
                    content=text,
                    source_ref=SourceRef(
                        source_id=source_id,
                        source_path=str(path),
                        locator="page {page}".format(page=index),
                    ),
                )
            )
        return SourceDocument(
            source_id=source_id,
            path=path,
            media_type=self.media_type,
            title=path.stem,
            sections=sections,
            extraction_warnings=warnings,
        )
