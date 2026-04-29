from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from docx import Document
from docx.document import Document as DocxDocument
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..core.models import DocumentSection, EmbeddedImage, ImageAnalysis, SourceDocument, SourceRef
from ..images.base import ImageAnalyzer
from .base import SourceAdapter

_BLIP_TAG = ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_EMBED_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
_MIME_TYPES_BY_SUFFIX = {
    ".gif": "image/gif",
    ".jpeg": "image/jpeg",
    ".jpg": "image/jpeg",
    ".png": "image/png",
    ".tif": "image/tiff",
    ".tiff": "image/tiff",
    ".webp": "image/webp",
}


def _nearest_non_empty_paragraph_text(
    paragraphs: List[Paragraph],
    start_index: int,
    step: int,
) -> str:
    index = start_index + step
    while 0 <= index < len(paragraphs):
        text = paragraphs[index].text.strip()
        if text:
            return text
        index += step
    return ""


def _dedupe_non_empty(items: List[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _mime_type_for_filename(filename: str) -> str:
    return _MIME_TYPES_BY_SUFFIX.get(PurePosixPath(filename).suffix.lower(), "application/octet-stream")


def _table_paragraphs(document: DocxDocument) -> List[Paragraph]:
    paragraphs: List[Paragraph] = []
    for table in document.tables:
        paragraphs.extend(_paragraphs_from_table(table))
    return paragraphs


def _paragraphs_from_table(table: Table) -> List[Paragraph]:
    paragraphs: List[Paragraph] = []
    for row in table.rows:
        for cell in row.cells:
            paragraphs.extend(cell.paragraphs)
            for nested_table in cell.tables:
                paragraphs.extend(_paragraphs_from_table(nested_table))
    return paragraphs


def _document_paragraphs_with_locations(document: DocxDocument) -> List[Tuple[str, int, Paragraph]]:
    located: List[Tuple[str, int, Paragraph]] = []
    for offset, paragraph in enumerate(document.paragraphs, start=1):
        located.append(("paragraph", offset, paragraph))
    for offset, paragraph in enumerate(_table_paragraphs(document), start=1):
        located.append(("table paragraph", offset, paragraph))
    return located


def _locator_for_image(image_index: int, location_kind: str, location_offset: int) -> str:
    if location_kind == "table paragraph":
        return "embedded image {index} near table paragraph {paragraph}".format(
            index=image_index,
            paragraph=location_offset,
        )
    return "embedded image {index} near paragraph {paragraph}".format(
        index=image_index,
        paragraph=location_offset,
    )


def _extract_embedded_images(
    document: DocxDocument,
    source_id: str,
    path: Path,
) -> List[EmbeddedImage]:
    located_paragraphs = _document_paragraphs_with_locations(document)
    paragraphs = [paragraph for _, _, paragraph in located_paragraphs]
    images: List[EmbeddedImage] = []
    image_index = 1
    for paragraph_offset, (location_kind, location_number, paragraph) in enumerate(located_paragraphs):
        caption = paragraph.text.strip()
        nearby_context = "\n".join(
            _dedupe_non_empty(
                [
                    _nearest_non_empty_paragraph_text(paragraphs, paragraph_offset, -1),
                    _nearest_non_empty_paragraph_text(paragraphs, paragraph_offset, 1),
                ]
            )
        )
        for run in paragraph.runs:
            for blip in run._element.findall(_BLIP_TAG):
                rel_id = str(blip.get(_EMBED_ATTR, "")).strip()
                if not rel_id:
                    continue
                relationship = document.part.rels.get(rel_id)
                image_part = document.part.related_parts.get(rel_id)
                if relationship is None or image_part is None:
                    continue
                filename = PurePosixPath(getattr(relationship, "target_ref", "")).name
                images.append(
                    EmbeddedImage(
                        image_id="{source_id}-image-{index}".format(
                            source_id=source_id,
                            index=image_index,
                        ),
                        source_ref=SourceRef(
                            source_id=source_id,
                            source_path=str(path),
                            locator=_locator_for_image(image_index, location_kind, location_number),
                        ),
                        filename=filename or "image-{index}".format(index=image_index),
                        mime_type=getattr(image_part, "content_type", "")
                        or _mime_type_for_filename(filename),
                        data=image_part.blob,
                        caption=caption,
                        context_text=nearby_context,
                    )
                )
                image_index += 1
    return images


def _render_image_analysis(image: EmbeddedImage, analysis: ImageAnalysis) -> str:
    lines = [
        "This section summarizes an embedded image from the source document.",
        "",
        "Visual summary: {summary}".format(summary=analysis.summary.strip()),
    ]
    if image.filename.strip():
        lines.extend(
            [
                "",
                "Image file: {filename}".format(filename=image.filename.strip()),
            ]
        )
    if image.caption.strip():
        lines.extend(
            [
                "",
                "Inline caption or nearby text: {caption}".format(caption=image.caption.strip()),
            ]
        )
    if image.context_text.strip():
        lines.extend(
            [
                "",
                "Nearby document context:",
                image.context_text.strip(),
            ]
        )
    if analysis.key_points:
        lines.extend(["", "Key visual details:"])
        lines.extend("- {point}".format(point=point) for point in analysis.key_points)
    return "\n".join(lines)


def _image_metadata_line(image: EmbeddedImage) -> str:
    return (
        "{locator}: file={filename}, mime={mime_type}, bytes={byte_count}"
    ).format(
        locator=image.source_ref.locator,
        filename=image.filename or "(unnamed)",
        mime_type=image.mime_type or "application/octet-stream",
        byte_count=len(image.data),
    )


class DocxAdapter(SourceAdapter):
    supported_suffixes = (".docx",)
    media_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

    def load(
        self,
        path: Path,
        image_analyzer: Optional[ImageAnalyzer] = None,
    ) -> SourceDocument:
        document = Document(str(path))
        paragraphs = [paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()]
        source_id = path.stem.replace(" ", "-").lower()
        sections: List[DocumentSection] = []
        if paragraphs:
            sections.append(
                DocumentSection(
                    heading=path.stem,
                    content="\n\n".join(paragraphs),
                    source_ref=SourceRef(
                        source_id=source_id,
                        source_path=str(path),
                        locator="document-body",
                    ),
                )
            )
        embedded_images = _extract_embedded_images(document=document, source_id=source_id, path=path)
        notes: List[str] = []
        warnings: List[str] = []
        if embedded_images:
            notes.append(
                "Detected {count} embedded image(s): {details}.".format(
                    count=len(embedded_images),
                    details="; ".join(_image_metadata_line(image) for image in embedded_images),
                )
            )
        if embedded_images and image_analyzer is None:
            warnings.append(
                "Detected {count} embedded image(s) but no image analyzer is configured; image content was skipped."
                .format(count=len(embedded_images))
            )
        if image_analyzer is not None:
            for index, image in enumerate(embedded_images, start=1):
                notes.append(
                    "Analyzing embedded image {index}: {details}.".format(
                        index=index,
                        details=_image_metadata_line(image),
                    )
                )
                try:
                    analysis = image_analyzer.analyze(image)
                    sections.append(
                        DocumentSection(
                            heading="Embedded image {index}".format(index=index),
                            content=_render_image_analysis(image, analysis),
                            source_ref=image.source_ref,
                            content_kind="image-analysis",
                        )
                    )
                    notes.append(
                        "Analyzed embedded image {index} successfully.".format(index=index)
                    )
                except Exception as error:
                    warnings.append(
                        "Failed to analyze embedded image {index}: {error}".format(
                            index=index,
                            error=error,
                        )
                    )
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
