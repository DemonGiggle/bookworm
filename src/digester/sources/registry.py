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
            PdfAdapter(),
            DocxAdapter(),
            SpreadsheetAdapter(),
            PlainTextAdapter(),
        ]

    def load_paths(
        self,
        paths: Iterable[Path],
        progress_reporter: Optional[ProgressReporter] = None,
        image_analyzer: Optional[ImageAnalyzer] = None,
        recursive_directories: bool = False,
    ) -> List[SourceDocument]:
        reporter = progress_reporter or NoOpProgressReporter()
        documents: List[SourceDocument] = []
        for path in paths:
            if path.is_dir():
                documents.extend(
                    self._load_directory(
                        path,
                        progress_reporter=reporter,
                        image_analyzer=image_analyzer,
                        recursive_directories=recursive_directories,
                    )
                )
                continue
            documents.append(self._load_file(path, reporter, image_analyzer=image_analyzer))
        return documents

    def _load_directory(
        self,
        path: Path,
        *,
        progress_reporter: ProgressReporter,
        image_analyzer: Optional[ImageAnalyzer],
        recursive_directories: bool,
    ) -> List[SourceDocument]:
        progress_reporter.persist("Scanning directory {name}.".format(name=file_label(path)))
        documents: List[SourceDocument] = []
        for child in sorted(path.iterdir()):
            if child.is_dir():
                if not recursive_directories:
                    progress_reporter.persist(
                        "Skipping nested directory {name}; pass --recursive to scan nested directories.".format(
                            name=file_label(child)
                        )
                    )
                    continue
                documents.extend(
                    self._load_directory(
                        child,
                        progress_reporter=progress_reporter,
                        image_analyzer=image_analyzer,
                        recursive_directories=True,
                    )
                )
                continue
            adapter = self._resolve_adapter(child)
            if adapter is None:
                progress_reporter.persist("Skipping unsupported file {name}.".format(name=file_label(child)))
                continue
            documents.append(
                self._load_file(
                    child,
                    progress_reporter,
                    adapter=adapter,
                    image_analyzer=image_analyzer,
                )
            )
        return documents

    def _load_file(
        self,
        path: Path,
        progress_reporter: ProgressReporter,
        *,
        adapter: Optional[SourceAdapter] = None,
        image_analyzer: Optional[ImageAnalyzer] = None,
    ) -> SourceDocument:
        resolved_adapter = adapter or self._require_adapter(path)
        progress_reporter.update(
            "Loading {name} with {adapter}.".format(
                name=file_label(path),
                adapter=resolved_adapter.__class__.__name__,
            )
        )
        document = resolved_adapter.load(path, image_analyzer=image_analyzer)
        progress_reporter.persist(
            "Loaded {name} with {sections} section(s).".format(
                name=file_label(path),
                sections=len(document.sections),
            )
        )
        for note in document.extraction_notes:
            progress_reporter.persist(
                "Note for {name}: {note}".format(
                    name=file_label(path),
                    note=note,
                )
            )
        for warning in document.extraction_warnings:
            progress_reporter.persist(
                "Warning for {name}: {warning}".format(
                    name=file_label(path),
                    warning=warning,
                )
            )
        return document

    def _resolve_adapter(self, path: Path) -> Optional[SourceAdapter]:
        for adapter in self.adapters:
            if adapter.supports(path):
                return adapter
        return None

    def _require_adapter(self, path: Path) -> SourceAdapter:
        adapter = self._resolve_adapter(path)
        if adapter is None:
            raise ValueError("Unsupported source type: {path}".format(path=path))
        return adapter
