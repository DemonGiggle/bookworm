from __future__ import annotations

from pathlib import Path

from docx import Document

from ..core.models import DocumentSection, SourceDocument, SourceRef
from .base import SourceAdapter


class DocxAdapter(SourceAdapter):
    supported_suffixes = (".docx",)
    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def load(self, path: Path) -> SourceDocument:
        document = Document(str(path))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        source_id = path.stem.replace(" ", "-").lower()
        return SourceDocument(
            source_id=source_id,
            path=path,
            media_type=self.media_type,
            title=path.stem,
            sections=[
                DocumentSection(
                    heading=path.stem,
                    content="\n\n".join(paragraphs),
                    source_ref=SourceRef(
                        source_id=source_id,
                        source_path=str(path),
                        locator="document-body",
                    ),
                )
            ],
        )
