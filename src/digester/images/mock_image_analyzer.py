from __future__ import annotations

from ..core.models import EmbeddedImage, ImageAnalysis
from .base import ImageAnalyzer


class MockImageAnalyzer(ImageAnalyzer):
    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model

    def analyze(self, image: EmbeddedImage) -> ImageAnalysis:
        label = image.caption.strip() or image.filename.strip() or image.source_ref.locator
        summary_lines = [
            "Analyzes the embedded image labeled {label} using deterministic fixture output.".format(
                label=label
            ),
            (
                "Mock image analysis preserves nearby document context and a traceable source reference "
                "without depending on a live vision model."
            ),
        ]
        key_points = []
        if image.caption.strip():
            key_points.append(
                "Inline caption or nearby text: {caption}".format(caption=image.caption.strip())
            )
        if image.context_text.strip():
            key_points.append(
                "Nearby document context: {context}".format(context=image.context_text.strip())
            )
        key_points.extend(
            [
                "Use a real vision-capable analyzer before relying on the visual summary for production decisions.",
                "Keep the cited image locator when comparing mock output to source material.",
            ]
        )
        return ImageAnalysis(summary="\n\n".join(summary_lines), key_points=key_points)
