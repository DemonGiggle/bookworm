from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import List, Optional

from pypdf import PdfReader

from ..core.models import DocumentSection, EmbeddedImage, SourceDocument, SourceRef
from ..images.base import ImageAnalyzer
from .base import SourceAdapter
from .embedded_images import analyze_embedded_images, mime_type_for_filename


def _extract_page_images(
    page,
    page_number: int,
    source_id: str,
    path: Path,
    image_offset: int,
    page_text: str,
) -> List[EmbeddedImage]:
    embedded_images: List[EmbeddedImage] = []
    for image in page.images:
        raw_name = str(getattr(image, "name", "")).strip()
        filename = PurePosixPath(raw_name).name if raw_name else "page-{page}-image-{index}".format(
            page=page_number,
            index=image_offset,
        )
        embedded_images.append(
            EmbeddedImage(
                image_id="{source_id}-image-{index}".format(
                    source_id=source_id,
                    index=image_offset,
                ),
                source_ref=SourceRef(
                    source_id=source_id,
                    source_path=str(path),
                    locator="embedded image {index} on page {page}".format(
                        index=image_offset,
                        page=page_number,
                    ),
                ),
                filename=filename,
                mime_type=mime_type_for_filename(filename),
                data=image.data,
                context_text=page_text,
            )
        )
        image_offset += 1
    return embedded_images


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
        embedded_images: List[EmbeddedImage] = []
        image_offset = 1
        for index, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
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
            else:
                warnings.append("Page {page} did not yield extractable text.".format(page=index))
            page_images = _extract_page_images(
                page=page,
                page_number=index,
                source_id=source_id,
                path=path,
                image_offset=image_offset,
                page_text=text,
            )
            embedded_images.extend(page_images)
            image_offset += len(page_images)
        notes, image_warnings = analyze_embedded_images(
            sections=sections,
            embedded_images=embedded_images,
            image_analyzer=image_analyzer,
        )
        warnings.extend(image_warnings)
        return SourceDocument(
            source_id=source_id,
            path=path,
            media_type=self.media_type,
            title=path.stem,
            sections=sections,
            embedded_images=embedded_images,
            extraction_notes=notes,
            extraction_warnings=warnings,
        )
