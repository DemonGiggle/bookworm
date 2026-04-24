from __future__ import annotations

from typing import Dict, List, Optional

from ..providers.base import LLMProvider
from .chunking import chunk_documents
from .models import (
    DigestBatchRequest,
    DigestConfig,
    DigestResult,
    SourceDocument,
    TopicDigest,
    collapse_topic_summary,
    ensure_topics_limited,
)


class DigestOrchestrator:
    def __init__(self, provider: LLMProvider, config: Optional[DigestConfig] = None) -> None:
        self.provider = provider
        self.config = config or DigestConfig()

    def run(self, documents: List[SourceDocument]) -> DigestResult:
        chunks = chunk_documents(documents, max_chunk_chars=self.config.max_chunk_chars)
        if not chunks:
            raise ValueError("No extractable text was found in the supplied inputs.")

        topic_map: Dict[str, TopicDigest] = {}
        stop_reason = "Processed all available chunks."
        total_batches = min(
            self.config.max_batches,
            (len(chunks) + self.config.batch_size - 1) // self.config.batch_size,
        )

        for batch_index in range(total_batches):
            start = batch_index * self.config.batch_size
            chunk_batch = chunks[start : start + self.config.batch_size]
            if not chunk_batch:
                break
            current_topics = ensure_topics_limited(list(topic_map.values()), self.config.max_topics)
            request = DigestBatchRequest(
                config=self.config,
                batch_number=batch_index + 1,
                total_batches=total_batches,
                chunk_batch=chunk_batch,
                current_topics=current_topics,
            )
            decision = self.provider.digest_batch(request)
            for update in decision.topic_updates:
                existing = topic_map.get(update.slug)
                if existing is None:
                    topic_map[update.slug] = update
                    continue
                existing.merge(update)
                existing.summary = collapse_topic_summary(existing.summary)
            if (
                not decision.should_continue
                and batch_index + 1 >= self.config.minimum_batches_before_stop
            ):
                stop_reason = decision.rationale or "Provider reported topic coverage was sufficient."
                break

        topics = ensure_topics_limited(
            self.provider.finalize_topics(list(topic_map.values())),
            self.config.max_topics,
        )
        if not topics:
            raise ValueError("The provider returned no topics for the supplied corpus.")
        return DigestResult(
            documents=documents,
            chunks=chunks,
            topics=topics,
            stop_reason=stop_reason,
        )
