from __future__ import annotations

import re
from pathlib import PurePath
from typing import Dict, List, Set, Tuple

from ..core.models import DigestBatchRequest, DigestDecision, SourceRef, TopicDigest
from .base import LLMProvider


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized or "mock-topic"


def _source_label(source_id: str, source_path: str) -> str:
    stem = PurePath(source_path).stem.strip()
    if stem:
        return stem.replace("-", " ").replace("_", " ")
    return source_id.replace("-", " ").replace("_", " ")


def _titleize(value: str) -> str:
    return " ".join(part.capitalize() for part in value.split())


class MockLLMProvider(LLMProvider):
    def __init__(self, model: str) -> None:
        super().__init__()
        self.model = model
        self._topic_slugs_by_source: Dict[Tuple[str, str], str] = {}
        self._used_topic_slugs: Set[str] = set()

    def _topic_slug_for(self, source_id: str, source_path: str) -> str:
        key = (source_id, source_path)
        existing = self._topic_slugs_by_source.get(key)
        if existing is not None:
            return existing

        base_slug = "mock-{source_id}".format(source_id=_slugify(source_id))
        candidate = base_slug
        suffix = 2
        while candidate in self._used_topic_slugs:
            candidate = "{base_slug}-{suffix}".format(base_slug=base_slug, suffix=suffix)
            suffix += 1

        self._used_topic_slugs.add(candidate)
        self._topic_slugs_by_source[key] = candidate
        return candidate

    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        if not request.chunk_batch:
            return DigestDecision(
                topic_updates=[],
                should_continue=False,
                rationale="MockLLM received an empty batch.",
            )

        grouped_refs: Dict[Tuple[str, str], List[SourceRef]] = {}
        grouped_seen: Dict[Tuple[str, str], Set[Tuple[str, str, str]]] = {}
        for chunk in request.chunk_batch:
            key = (chunk.source_id, chunk.source_path)
            refs = grouped_refs.setdefault(key, [])
            seen = grouped_seen.setdefault(key, set())
            ref_key = (
                chunk.source_ref.source_id,
                chunk.source_ref.source_path,
                chunk.source_ref.locator,
            )
            if ref_key in seen:
                continue
            seen.add(ref_key)
            refs.append(chunk.source_ref)

        topic_updates: List[TopicDigest] = []
        for source_id, source_path in grouped_refs:
            label = _source_label(source_id=source_id, source_path=source_path)
            topic_updates.append(
                TopicDigest(
                    slug=self._topic_slug_for(source_id=source_id, source_path=source_path),
                    title="Mock {label}".format(label=_titleize(label)),
                    summary=(
                        "end-to-end validation for {label} without a real LLM response.\n\n"
                        "MockLLM generated this placeholder from source metadata and preserved "
                        "references without semantically parsing the document content."
                    ).format(label=label),
                    key_points=[
                        "Treat this topic as synthetic fixture output for ingestion, orchestration, and artifact export checks.",
                        "MockLLM keeps real source references so downstream skills still point at the original files.",
                        "Switch to a real provider before using generated summaries for implementation or product decisions.",
                    ],
                    references=grouped_refs[(source_id, source_path)],
                )
            )

        should_continue = request.batch_number < request.total_batches
        rationale = (
            "MockLLM continues through the remaining batches to exercise the full pipeline."
            if should_continue
            else "MockLLM reached the final batch and finalized the placeholder topics."
        )
        return DigestDecision(
            topic_updates=topic_updates,
            should_continue=should_continue,
            rationale=rationale,
        )

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        return sorted(topics, key=lambda topic: topic.slug)
