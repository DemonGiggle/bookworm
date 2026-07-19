from __future__ import annotations

from typing import Callable, Iterable, List, Optional

from .models import ContentChunk, SourceDocument


TokenCounter = Callable[[str], int]


def estimate_tokens(text: str) -> int:
    """Conservatively estimate tokens when a model tokenizer is unavailable."""
    if not text:
        return 0
    return max(1, (len(text.encode("utf-8", errors="replace")) + 2) // 3)


def _within_budget(
    text: str,
    max_chunk_chars: Optional[int],
    max_chunk_tokens: Optional[int],
    token_counter: TokenCounter,
) -> bool:
    if max_chunk_chars is not None and len(text) > max_chunk_chars:
        return False
    if max_chunk_tokens is not None and token_counter(text) > max_chunk_tokens:
        return False
    return True


def _hard_split(
    text: str,
    max_chunk_chars: Optional[int],
    max_chunk_tokens: Optional[int],
    token_counter: TokenCounter,
) -> List[str]:
    pieces: List[str] = []
    remaining = text
    while remaining:
        high = 1
        while high <= len(remaining) and _within_budget(
            remaining[:high],
            max_chunk_chars,
            max_chunk_tokens,
            token_counter,
        ):
            high *= 2
        low = max(1, high // 2)
        high = min(high, len(remaining))
        best = 0
        while low <= high:
            middle = (low + high) // 2
            if _within_budget(
                remaining[:middle],
                max_chunk_chars,
                max_chunk_tokens,
                token_counter,
            ):
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best == 0:
            raise ValueError("Chunk budget is too small to fit one character.")
        pieces.append(remaining[:best])
        remaining = remaining[best:]
    return pieces


def _split_oversized_block(
    block: str,
    max_chunk_chars: Optional[int],
    max_chunk_tokens: Optional[int],
    token_counter: TokenCounter,
) -> List[str]:
    if _within_budget(block, max_chunk_chars, max_chunk_tokens, token_counter):
        return [block]

    return _hard_split(block, max_chunk_chars, max_chunk_tokens, token_counter)


def _bounded_units(
    content: str,
    max_chunk_chars: Optional[int],
    max_chunk_tokens: Optional[int],
    token_counter: TokenCounter,
) -> Iterable[str]:
    paragraphs = [part.strip() for part in content.split("\n\n") if part.strip()]
    if not paragraphs and content.strip():
        paragraphs = [content.strip()]
    for paragraph in paragraphs:
        yield from _split_oversized_block(
            paragraph,
            max_chunk_chars,
            max_chunk_tokens,
            token_counter,
        )


def chunk_documents(
    documents: List[SourceDocument],
    max_chunk_chars: Optional[int] = 1800,
    max_chunk_tokens: Optional[int] = None,
    token_counter: Optional[TokenCounter] = None,
) -> List[ContentChunk]:
    if max_chunk_chars is not None and max_chunk_chars <= 0:
        raise ValueError("max_chunk_chars must be positive when configured.")
    if max_chunk_tokens is not None and max_chunk_tokens <= 0:
        raise ValueError("max_chunk_tokens must be positive when configured.")
    if max_chunk_chars is None and max_chunk_tokens is None:
        raise ValueError("At least one chunk budget must be configured.")

    count_tokens = token_counter or estimate_tokens
    chunks: List[ContentChunk] = []
    for document in documents:
        chunk_index = 1
        for section in document.sections:
            current_parts: List[str] = []
            for unit in _bounded_units(
                section.content,
                max_chunk_chars,
                max_chunk_tokens,
                count_tokens,
            ):
                candidate = "\n\n".join(current_parts + [unit])
                if current_parts and not _within_budget(
                    candidate,
                    max_chunk_chars,
                    max_chunk_tokens,
                    count_tokens,
                ):
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
                current_parts.append(unit)
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
