from __future__ import annotations

from pathlib import Path

from ..core.models import DocumentSection, SourceDocument, SourceRef
from .base import SourceAdapter


class PlainTextAdapter(SourceAdapter):
    supported_suffixes = (".txt", ".md", ".rst")
    media_type = "text/plain"

    def load(self, path: Path) -> SourceDocument:
        content = path.read_text(encoding="utf-8")
        source_id = path.stem.replace(" ", "-").lower()
        return SourceDocument(
            source_id=source_id,
            path=path,
            media_type=self.media_type,
            title=path.stem,
            sections=[
                DocumentSection(
                    heading=path.stem,
                    content=content,
                    source_ref=SourceRef(
                        source_id=source_id,
                        source_path=str(path),
                        locator="full-document",
                    ),
                )
            ],
        )
