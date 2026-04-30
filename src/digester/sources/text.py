from __future__ import annotations

from pathlib import Path
from typing import Optional

from ..core.models import DocumentSection, SourceDocument, SourceRef
from ..images.base import ImageAnalyzer
from .base import SourceAdapter


class PlainTextAdapter(SourceAdapter):
    supported_suffixes = (
        ".txt",
        ".md",
        ".rst",
        ".py",
        ".pyi",
        ".js",
        ".jsx",
        ".ts",
        ".tsx",
        ".java",
        ".kt",
        ".kts",
        ".go",
        ".rs",
        ".c",
        ".h",
        ".cc",
        ".hh",
        ".cpp",
        ".hpp",
        ".cxx",
        ".hxx",
        ".cs",
        ".php",
        ".rb",
        ".swift",
        ".scala",
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".sql",
        ".html",
        ".css",
        ".scss",
        ".sass",
        ".less",
        ".xml",
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".ini",
        ".cfg",
        ".conf",
    )
    media_type = "text/plain"
    supported_filenames = (
        "dockerfile",
        "makefile",
        "jenkinsfile",
        "procfile",
        "vagrantfile",
        "gemfile",
        "rakefile",
        ".env",
        ".gitignore",
        ".gitattributes",
        ".editorconfig",
    )

    def supports(self, path: Path) -> bool:
        if super().supports(path):
            return True
        lowered_name = path.name.lower()
        if lowered_name in self.supported_filenames or lowered_name.startswith(".env."):
            return True
        return _looks_like_utf8_text(path)

    def load(
        self,
        path: Path,
        image_analyzer: Optional[ImageAnalyzer] = None,
    ) -> SourceDocument:
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


def _looks_like_utf8_text(path: Path, sample_size: int = 8192) -> bool:
    try:
        with path.open("rb") as stream:
            sample = stream.read(sample_size)
    except OSError:
        return False
    if not sample:
        return True
    if b"\x00" in sample:
        return False
    try:
        sample.decode("utf-8")
    except UnicodeDecodeError:
        return False
    return True
