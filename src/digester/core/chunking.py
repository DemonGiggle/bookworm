from __future__ import annotations

from typing import List

from .models import ContentChunk, SourceDocument


def chunk_documents(documents: List[SourceDocument], max_chunk_chars: int) -> List[ContentChunk]:
    chunks: List[ContentChunk] = []
    for document in documents:
        chunk_index = 1
        for section in document.sections:
            paragraphs = [paragraph.strip() for paragraph in section.content.split("\n\n") if paragraph.strip()]
            if not paragraphs and section.content.strip():
                paragraphs = [section.content.strip()]
            current_parts = []
            current_size = 0
            for paragraph in paragraphs:
                paragraph_size = len(paragraph)
                if current_parts and current_size + paragraph_size + 2 > max_chunk_chars:
                    chunks.append(
                        ContentChunk(
                            chunk_id="{source_id}-chunk-{index}".format(
                                source_id=document.source_id,
                                index=chunk_index,
                            ),
                            source_id=document.source_id,
                            source_path=document.path_str,
                            section_heading=section.heading,
                            text="\n\n".join(current_parts),
                            source_ref=section.source_ref,
                            content_kind=section.content_kind,
                        )
                    )
                    chunk_index += 1
                    current_parts = []
                    current_size = 0
                current_parts.append(paragraph)
                current_size += paragraph_size + 2
            if current_parts:
                chunks.append(
                    ContentChunk(
                        chunk_id="{source_id}-chunk-{index}".format(
                            source_id=document.source_id,
                            index=chunk_index,
                        ),
                        source_id=document.source_id,
                        source_path=document.path_str,
                        section_heading=section.heading,
                        text="\n\n".join(current_parts),
                        source_ref=section.source_ref,
                        content_kind=section.content_kind,
                    )
                )
                chunk_index += 1
    return chunks
