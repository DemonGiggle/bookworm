from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence

from ..providers.base import LLMProvider
from ..utils.progress import NoOpProgressReporter, ProgressReporter, file_label
from .chunking import chunk_documents
from .models import (
    DigestBatchRequest,
    DigestConfig,
    DigestResult,
    SourceDocument,
    TopicDigest,
    collapse_topic_summary,
    ensure_topics_limited,
    validate_topics_for_export,
)


class DigestOrchestrator:
    def __init__(
        self,
        provider: LLMProvider,
        config: Optional[DigestConfig] = None,
        progress_reporter: Optional[ProgressReporter] = None,
    ) -> None:
        self.provider = provider
        self.config = config or DigestConfig()
        self.progress_reporter = progress_reporter or NoOpProgressReporter()

    def run(
        self,
        documents: List[SourceDocument],
        on_topics_finalized: Optional[Callable[[Sequence[TopicDigest]], None]] = None,
        on_topics_updated: Optional[Callable[[Sequence[TopicDigest]], None]] = None,
    ) -> DigestResult:
        self.progress_reporter.update(
            "Chunking {count} loaded document(s).".format(count=len(documents))
        )
        chunks = chunk_documents(documents, max_chunk_chars=self.config.max_chunk_chars)
        if not chunks:
            raise ValueError("No extractable text was found in the supplied inputs.")

        self.progress_reporter.persist(
            "Prepared {chunks} chunk(s) from {documents} document(s).".format(
                chunks=len(chunks),
                documents=len(documents),
            )
        )

        topic_map: Dict[str, TopicDigest] = {}
        finalized_topics: Dict[str, TopicDigest] = {}
        finalized_topic_order: List[str] = []
        active_topic_slugs: List[str] = []
        stop_reason = "Processed all available chunks."
        available_batches = (len(chunks) + self.config.batch_size - 1) // self.config.batch_size
        total_batches = min(
            self.config.max_batches,
            available_batches,
        )

        def flush_topic_cluster(reason: Optional[str] = None) -> None:
            if not topic_map:
                return
            finalized = self.provider.finalize_topics(list(topic_map.values()))
            topics = validate_topics_for_export(finalized)
            if not topics:
                raise ValueError("The provider returned no topics for the supplied corpus.")
            self.progress_reporter.persist(
                "Finalized {count} topic digest(s).".format(count=len(topics))
            )
            if reason:
                self.progress_reporter.persist(reason)
            for topic in topics:
                if topic.slug not in finalized_topics:
                    finalized_topic_order.append(topic.slug)
                finalized_topics[topic.slug] = topic
            if on_topics_finalized is not None:
                on_topics_finalized(topics)
            topic_map.clear()
            active_topic_slugs.clear()

        try:
            for batch_index in range(total_batches):
                start = batch_index * self.config.batch_size
                chunk_batch = chunks[start : start + self.config.batch_size]
                if not chunk_batch:
                    break
                current_topics = ensure_topics_limited(
                    [topic_map[slug] for slug in active_topic_slugs if slug in topic_map],
                    self.config.max_active_topics,
                )
                batch_files = sorted({file_label(chunk.source_path) for chunk in chunk_batch})
                self.progress_reporter.update(
                    "Digesting batch {current}/{total} for {files}.".format(
                        current=batch_index + 1,
                        total=total_batches,
                        files=", ".join(batch_files),
                    )
                )
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
                        if update.slug in active_topic_slugs:
                            active_topic_slugs.remove(update.slug)
                        active_topic_slugs.append(update.slug)
                        continue
                    existing.merge(update)
                    existing.summary = collapse_topic_summary(existing.summary)
                    if update.slug in active_topic_slugs:
                        active_topic_slugs.remove(update.slug)
                    active_topic_slugs.append(update.slug)
                self.progress_reporter.persist(
                    "Completed batch {current}/{total}; tracking {topics} topic(s).".format(
                        current=batch_index + 1,
                        total=total_batches,
                        topics=len(topic_map),
                    )
                )
                if topic_map and on_topics_updated is not None:
                    on_topics_updated(list(topic_map.values()))
                if (
                    not decision.should_continue
                    and batch_index + 1 >= self.config.minimum_batches_before_stop
                ):
                    flush_topic_cluster(
                        "Batch {current}/{total} marked the current topic cluster as complete: {reason}".format(
                            current=batch_index + 1,
                            total=total_batches,
                            reason=decision.rationale
                            or "Provider reported the visible section-like topics looked complete.",
                        ),
                    )

            self.progress_reporter.update("Finalizing topic digests.")
            flush_topic_cluster()
        except Exception:
            if topic_map and on_topics_updated is not None:
                self.progress_reporter.persist(
                    "Persisting {count} in-progress topic digest(s) after an error.".format(
                        count=len(topic_map)
                    )
                )
                on_topics_updated(list(topic_map.values()))
            raise
        topics = [finalized_topics[slug] for slug in finalized_topic_order]
        if not topics:
            raise ValueError("The provider returned no topics for the supplied corpus.")
        if total_batches < available_batches:
            stop_reason = "Reached max_batches before processing all available chunks."
        return DigestResult(
            documents=documents,
            chunks=chunks,
            topics=topics,
            stop_reason=stop_reason,
        )
