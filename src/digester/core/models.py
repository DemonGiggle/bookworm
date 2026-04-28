from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence


def _dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        normalized = item.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)
    return result


def _dedupe_source_refs(refs: Iterable["SourceRef"]) -> List["SourceRef"]:
    seen = set()
    ordered_refs: List[SourceRef] = []
    for ref in refs:
        key = (ref.source_id, ref.source_path, ref.locator)
        if key in seen:
            continue
        seen.add(key)
        ordered_refs.append(ref)
    return ordered_refs


def _merge_prefer_richer_text(current: str, update: str) -> str:
    current = current.strip()
    update = update.strip()
    if not update:
        return current
    if not current:
        return update
    if current == update:
        return current
    if len(update) > len(current):
        return update
    return current


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    source_path: str
    locator: str

    def render(self) -> str:
        return "{path} ({locator})".format(path=self.source_path, locator=self.locator)


@dataclass
class DocumentSection:
    heading: str
    content: str
    source_ref: SourceRef


@dataclass
class SourceDocument:
    source_id: str
    path: Path
    media_type: str
    title: str
    sections: List[DocumentSection]
    extraction_warnings: List[str] = field(default_factory=list)

    @property
    def path_str(self) -> str:
        return str(self.path)


@dataclass
class ContentChunk:
    chunk_id: str
    source_id: str
    source_path: str
    section_heading: str
    text: str
    source_ref: SourceRef


@dataclass
class TopicDigest:
    slug: str
    title: str
    summary: str
    routing_description: str = ""
    key_points: List[str] = field(default_factory=list)
    workflow_notes: List[str] = field(default_factory=list)
    references: List[SourceRef] = field(default_factory=list)

    def merge(self, other: "TopicDigest") -> None:
        self.routing_description = _merge_prefer_richer_text(
            self.routing_description,
            other.routing_description,
        )
        if other.summary:
            if self.summary:
                self.summary = "{current}\n\n{update}".format(
                    current=self.summary.strip(),
                    update=other.summary.strip(),
                ).strip()
            else:
                self.summary = other.summary.strip()
        self.key_points = _dedupe_preserve_order(self.key_points + other.key_points)
        self.workflow_notes = _dedupe_preserve_order(self.workflow_notes + other.workflow_notes)
        self.references = _dedupe_source_refs(self.references + other.references)


@dataclass
class DigestConfig:
    max_chunk_chars: int = 1800
    batch_size: int = 2
    minimum_batches_before_stop: int = 2
    max_batches: int = 50
    max_active_topics: int = 12
    max_topics: Optional[int] = None

    def __post_init__(self) -> None:
        if self.max_topics is not None:
            self.max_active_topics = self.max_topics


@dataclass
class DigestBatchRequest:
    config: DigestConfig
    batch_number: int
    total_batches: int
    chunk_batch: Sequence[ContentChunk]
    current_topics: Sequence[TopicDigest]


@dataclass
class DigestDecision:
    topic_updates: List[TopicDigest]
    should_continue: bool
    rationale: str

    @classmethod
    def from_payload(
        cls,
        payload: Dict[str, object],
        fallback_refs: Sequence[SourceRef],
    ) -> "DigestDecision":
        topic_updates: List[TopicDigest] = []
        raw_topics = payload.get("topic_updates", [])
        if isinstance(raw_topics, list):
            for raw_topic in raw_topics:
                if not isinstance(raw_topic, dict):
                    continue
                refs = raw_topic.get("references", [])
                parsed_refs: List[SourceRef] = []
                if isinstance(refs, list):
                    for ref in refs:
                        if not isinstance(ref, dict):
                            continue
                        source_id = str(ref.get("source_id", "")).strip()
                        source_path = str(ref.get("source_path", "")).strip()
                        locator = str(ref.get("locator", "")).strip()
                        if source_id and source_path and locator:
                            parsed_refs.append(
                                SourceRef(
                                    source_id=source_id,
                                    source_path=source_path,
                                    locator=locator,
                                )
                            )
                if not parsed_refs:
                    parsed_refs = list(fallback_refs)
                key_points = raw_topic.get("key_points", [])
                workflow_notes = raw_topic.get("workflow_notes", [])
                topic_updates.append(
                    TopicDigest(
                        slug=str(raw_topic.get("slug", "")).strip(),
                        title=str(raw_topic.get("title", "")).strip(),
                        routing_description=str(
                            raw_topic.get("routing_description") or raw_topic.get("when_to_use") or ""
                        ).strip(),
                        summary=str(raw_topic.get("summary", "")).strip(),
                        key_points=[str(point).strip() for point in key_points or [] if str(point).strip()],
                        workflow_notes=[
                            str(note).strip() for note in workflow_notes or [] if str(note).strip()
                        ],
                        references=parsed_refs,
                    )
                )
        return cls(
            topic_updates=[topic for topic in topic_updates if topic.slug and topic.title],
            should_continue=bool(payload.get("should_continue", True)),
            rationale=str(payload.get("rationale", "")).strip(),
        )


@dataclass
class DigestResult:
    documents: Sequence[SourceDocument]
    chunks: Sequence[ContentChunk]
    topics: Sequence[TopicDigest]
    stop_reason: str
    artifact_paths: Dict[str, Path] = field(default_factory=dict)


def ensure_topics_limited(topics: Sequence[TopicDigest], max_topics: int) -> List[TopicDigest]:
    if max_topics <= 0:
        return []
    return list(topics[-max_topics:])


def collapse_topic_summary(summary: str) -> str:
    return "\n".join(_dedupe_preserve_order(summary.splitlines())).strip()


def combine_references(topics: Sequence[TopicDigest]) -> List[SourceRef]:
    refs: List[SourceRef] = []
    for topic in topics:
        refs.extend(topic.references)
    return _dedupe_source_refs(refs)


def topic_lookup(topics: Sequence[TopicDigest]) -> Dict[str, TopicDigest]:
    return {topic.slug: topic for topic in topics}
