from __future__ import annotations

from pathlib import Path
from typing import Iterable, List, Optional

from ..core.models import SourceDocument
from ..images.base import ImageAnalyzer
from ..utils.progress import NoOpProgressReporter, ProgressReporter, file_label
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

    def load_paths(
        self,
        paths: Iterable[Path],
        progress_reporter: Optional[ProgressReporter] = None,
        image_analyzer: Optional[ImageAnalyzer] = None,
    ) -> List[SourceDocument]:
        reporter = progress_reporter or NoOpProgressReporter()
        documents: List[SourceDocument] = []
        for path in paths:
            if path.is_dir():
                reporter.persist("Scanning directory {name}.".format(name=file_label(path)))
                documents.extend(
                    self.load_paths(
                        sorted(child for child in path.iterdir()),
                        progress_reporter=reporter,
                        image_analyzer=image_analyzer,
                    )
                )
                continue
            adapter = self._resolve_adapter(path)
            reporter.update(
                "Loading {name} with {adapter}.".format(
                    name=file_label(path),
                    adapter=adapter.__class__.__name__,
                )
            )
            document = adapter.load(path, image_analyzer=image_analyzer)
            documents.append(document)
            reporter.persist(
                "Loaded {name} with {sections} section(s).".format(
                    name=file_label(path),
                    sections=len(document.sections),
                )
            )
            for note in document.extraction_notes:
                reporter.persist(
                    "Note for {name}: {note}".format(
                        name=file_label(path),
                        note=note,
                    )
                )
            for warning in document.extraction_warnings:
                reporter.persist(
                    "Warning for {name}: {warning}".format(
                        name=file_label(path),
                        warning=warning,
                    )
                )
        return documents

    def _resolve_adapter(self, path: Path) -> SourceAdapter:
        for adapter in self.adapters:
            if adapter.supports(path):
                return adapter
        raise ValueError("Unsupported source type: {path}".format(path=path))
