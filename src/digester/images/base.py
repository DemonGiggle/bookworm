from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from ..core.models import EmbeddedImage, ImageAnalysis
from ..utils.progress import NoOpProgressReporter, ProgressReporter


class ImageAnalyzer(ABC):
    def __init__(self, progress_reporter: Optional[ProgressReporter] = None) -> None:
        self.progress_reporter = progress_reporter or NoOpProgressReporter()

    def set_progress_reporter(self, progress_reporter: Optional[ProgressReporter]) -> None:
        self.progress_reporter = progress_reporter or NoOpProgressReporter()

    def validate_configuration(self) -> None:
        return None

    @abstractmethod
    def analyze(self, image: EmbeddedImage) -> ImageAnalysis:
        raise NotImplementedError
