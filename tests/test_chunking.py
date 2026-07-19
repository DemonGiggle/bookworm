from pathlib import Path

import pytest

from digester.core.chunking import chunk_documents, estimate_tokens
from digester.core.models import DigestConfig, DocumentSection, SourceDocument, SourceRef


def _document(content: str, content_kind: str = "text") -> SourceDocument:
    return SourceDocument(
        source_id="sample",
        path=Path("sample.txt"),
        media_type="text/plain",
        title="sample",
        sections=[
            DocumentSection(
                heading="Content",
                content=content,
                source_ref=SourceRef(
                    source_id="sample",
                    source_path="sample.txt",
                    locator="full-document",
                ),
                content_kind=content_kind,
            )
        ],
    )


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


@pytest.mark.parametrize(
    "content",
    [
        "這是一段沒有空行的中文內容" * 20,
        "def example(value):\n    return value * 2\n" * 30,
        "name\tvalue\tstatus\nitem\t123\tready\n" * 30,
        "X" * 1000,
    ],
)
def test_token_budget_hard_splits_multilingual_and_structured_content(content: str) -> None:
    chunks = chunk_documents(
        [_document(content)],
        max_chunk_chars=None,
        max_chunk_tokens=25,
    )

    assert len(chunks) > 1
    assert all(estimate_tokens(chunk.text) <= 25 for chunk in chunks)
    assert all(chunk.source_ref.locator == "full-document" for chunk in chunks)
    assert "".join(chunk.text.replace("\n\n", "") for chunk in chunks).replace(
        "\n", ""
    ) == content.replace("\n", "")


def test_character_budget_is_a_hard_limit_for_one_oversized_paragraph() -> None:
    chunks = chunk_documents([_document("A" * 125)], max_chunk_chars=40)

    assert [len(chunk.text) for chunk in chunks] == [40, 40, 40, 5]


def test_chunker_accepts_provider_specific_token_counter() -> None:
    def two_chars_per_token(text: str) -> int:
        return (len(text) + 1) // 2

    chunks = chunk_documents(
        [_document("A" * 35)],
        max_chunk_chars=None,
        max_chunk_tokens=5,
        token_counter=two_chars_per_token,
    )

    assert all(two_chars_per_token(chunk.text) <= 5 for chunk in chunks)
    assert [len(chunk.text) for chunk in chunks] == [10, 10, 10, 5]


def test_digest_config_allows_disabling_character_budget() -> None:
    config = DigestConfig(max_chunk_chars=None, max_chunk_tokens=20)

    assert config.max_chunk_chars is None


def test_token_estimator_handles_lone_surrogates() -> None:
    assert estimate_tokens("valid\ud800text") > 0


@pytest.mark.parametrize(
    ("context_window", "reserved", "batch_size", "expected"),
    [
        (8192, 4096, 2, 2048),
        (32768, 8192, 4, 6144),
    ],
)
def test_digest_config_reserves_context_per_batch(
    context_window: int,
    reserved: int,
    batch_size: int,
    expected: int,
) -> None:
    config = DigestConfig(
        context_window_tokens=context_window,
        reserved_context_tokens=reserved,
        batch_size=batch_size,
    )

    assert config.max_chunk_tokens == expected
