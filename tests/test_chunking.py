from pathlib import Path

from digester.core.chunking import chunk_documents
from digester.core.models import DocumentSection, SourceDocument, SourceRef


def test_chunk_documents_splits_large_sections() -> None:
    document = SourceDocument(
        source_id="sample",
        path=Path("sample.txt"),
        media_type="text/plain",
        title="sample",
        sections=[
            DocumentSection(
                heading="Intro",
                content="A" * 40 + "\n\n" + "B" * 40 + "\n\n" + "C" * 40,
                source_ref=SourceRef(source_id="sample", source_path="sample.txt", locator="full-document"),
            )
        ],
    )

    chunks = chunk_documents([document], max_chunk_chars=60)

    assert len(chunks) == 3
    assert chunks[0].chunk_id == "sample-chunk-1"
    assert chunks[-1].text == "C" * 40
    assert all(chunk.content_kind == "text" for chunk in chunks)


def test_chunk_documents_preserves_section_content_kind() -> None:
    document = SourceDocument(
        source_id="sample",
        path=Path("sample.txt"),
        media_type="text/plain",
        title="sample",
        sections=[
            DocumentSection(
                heading="Embedded image 1",
                content="Visual summary: The dialog shows a confirm button.",
                source_ref=SourceRef(source_id="sample", source_path="sample.txt", locator="embedded image 1"),
                content_kind="image-analysis",
            )
        ],
    )

    chunks = chunk_documents([document], max_chunk_chars=200)

    assert len(chunks) == 1
    assert chunks[0].content_kind == "image-analysis"
