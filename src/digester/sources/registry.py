from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

from ..core.models import SourceDocument
from .base import SourceAdapter
from .docx import DocxAdapter
from .pdf import PdfAdapter
from .spreadsheet import SpreadsheetAdapter
from .text import PlainTextAdapter


class SourceRegistry:
    def __init__(self, adapters: Optional[Iterable[SourceAdapter]] = None) -> None:
        self.adapters = list(adapters or self.default_adapters())

    @staticmethod
    def default_adapters() -> List[SourceAdapter]:
        return [
            PlainTextAdapter(),
            PdfAdapter(),
            DocxAdapter(),
            SpreadsheetAdapter(),
        ]

    def load_paths(self, paths: Iterable[Path]) -> List[SourceDocument]:
        documents: List[SourceDocument] = []
        for path in paths:
            if path.is_dir():
                documents.extend(self.load_paths(sorted(child for child in path.iterdir() if child.is_file())))
                continue
            adapter = self._resolve_adapter(path)
            documents.append(adapter.load(path))
        return documents

    def _resolve_adapter(self, path: Path) -> SourceAdapter:
        for adapter in self.adapters:
            if adapter.supports(path):
                return adapter
        raise ValueError("Unsupported source type: {path}".format(path=path))
