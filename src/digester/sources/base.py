from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Tuple

from ..core.models import SourceDocument
from ..images.base import ImageAnalyzer


class SourceAdapter(ABC):
    supported_suffixes: Tuple[str, ...] = ()
    media_type: str = "application/octet-stream"

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in self.supported_suffixes

    @abstractmethod
    def load(
        self,
        path: Path,
        image_analyzer: Optional[ImageAnalyzer] = None,
    ) -> SourceDocument:
        raise NotImplementedError
