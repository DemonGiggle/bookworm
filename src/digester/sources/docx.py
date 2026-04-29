from __future__ import annotations

from pathlib import Path, PurePosixPath
from typing import List, Optional, Tuple

from docx import Document
from docx.document import Document as DocxDocument
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from ..core.models import DocumentSection, EmbeddedImage, SourceDocument, SourceRef
from ..images.base import ImageAnalyzer
from .base import SourceAdapter
from .embedded_images import analyze_embedded_images, mime_type_for_filename

_BLIP_TAG = ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
_VML_IMAGE_TAG = ".//{urn:schemas-microsoft-com:vml}imagedata"
_EMBED_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed"
_RELATIONSHIP_ID_ATTR = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
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
def _paragraphs_from_table(table: Table) -> List[Paragraph]:
    paragraphs: List[Paragraph] = []
    seen_cells = set()
    for row in table.rows:
        for cell in row.cells:
            if cell._tc in seen_cells:
                continue
            seen_cells.add(cell._tc)
            paragraphs.extend(cell.paragraphs)
            for nested_table in cell.tables:
                paragraphs.extend(_paragraphs_from_table(nested_table))
    return paragraphs


def _document_paragraphs_with_locations(document: DocxDocument) -> List[Tuple[str, int, Paragraph]]:
    located: List[Tuple[str, int, Paragraph]] = []
    paragraph_offset = 0
    table_paragraph_offset = 0
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            paragraph_offset += 1
            located.append(("paragraph", paragraph_offset, Paragraph(child, document)))
            continue
        if isinstance(child, CT_Tbl):
            for paragraph in _paragraphs_from_table(Table(child, document)):
                table_paragraph_offset += 1
                located.append(("table paragraph", table_paragraph_offset, paragraph))
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


def _image_relationship_ids(run) -> List[str]:
    rel_ids: List[str] = []
    for blip in run._element.findall(_BLIP_TAG):
        rel_id = str(blip.get(_EMBED_ATTR, "")).strip()
        if rel_id:
            rel_ids.append(rel_id)
    for image_data in run._element.findall(_VML_IMAGE_TAG):
        rel_id = str(image_data.get(_RELATIONSHIP_ID_ATTR, "")).strip()
        if rel_id:
            rel_ids.append(rel_id)
    return rel_ids


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
            for rel_id in _image_relationship_ids(run):
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
                        or mime_type_for_filename(filename),
                        data=image_part.blob,
                        caption=caption,
                        context_text=nearby_context,
                    )
                )
                image_index += 1
    return images
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
        notes, warnings = analyze_embedded_images(
            sections=sections,
            embedded_images=embedded_images,
            image_analyzer=image_analyzer,
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
