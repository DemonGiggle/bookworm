from pathlib import Path
from typing import List

from digester.core import DigestConfig
from digester.core.models import DigestBatchRequest, DigestDecision, TopicDigest
from digester.interfaces.api import DocumentDigester
from digester.providers.base import LLMProvider


class FakeProvider(LLMProvider):
    def __init__(self) -> None:
        self.calls = 0

    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        self.calls += 1
        topic = TopicDigest(
            slug="architecture",
            title="Architecture",
            summary=(
                "Summarizes the system design and interfaces.\n\n"
                "Includes enough operational detail to help another engineer follow the setup flow."
            ),
            key_points=[
                "Uses adapters for ingestion",
                "Emits section-like skill files",
                "Preserves setup detail for downstream readers",
            ],
            references=[chunk.source_ref for chunk in request.chunk_batch],
        )
        should_continue = self.calls < 2
        return DigestDecision(
            topic_updates=[topic],
            should_continue=should_continue,
            rationale="Topic coverage is sufficient after two batches.",
        )

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        return topics


class RecordingReporter:
    def __init__(self) -> None:
        self.messages = []

    def update(self, message: str) -> None:
        self.messages.append(("update", message))

    def persist(self, message: str) -> None:
        self.messages.append(("persist", message))

    def clear(self) -> None:
        self.messages.append(("clear", ""))


def test_document_digester_writes_topic_files_and_index(tmp_path: Path) -> None:
    input_path = tmp_path / "source.txt"
    input_path.write_text(
        "The digester ingests files.\n\n"
        "It loops with an LLM to decide whether more content is required.\n\n"
        "It writes concise markdown artifacts for downstream agents.",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"
    reporter = RecordingReporter()

    provider = FakeProvider()
    result = DocumentDigester(
        provider=provider,
        config=DigestConfig(max_chunk_chars=70, batch_size=1, minimum_batches_before_stop=2),
        progress_reporter=reporter,
    ).digest_paths([input_path], output_dir)

    topic_text = (output_dir / "architecture.md").read_text(encoding="utf-8")
    index_text = (output_dir / "INDEX.md").read_text(encoding="utf-8")

    assert (output_dir / "architecture.md").exists()
    assert (output_dir / "INDEX.md").exists()
    assert "Architecture" in index_text
    assert "## Overview" in topic_text
    assert "## Detailed takeaways" in topic_text
    assert "## Source files" in topic_text
    assert result.stop_reason == "Processed all available chunks."
    assert provider.calls == 3
    persisted = [message for kind, message in reporter.messages if kind == "persist"]
    assert any("Loaded source.txt with 1 section(s)." == message for message in persisted)
    assert any("Prepared 3 chunk(s) from 1 document(s)." == message for message in persisted)
    assert any("Completed batch 3/3; tracking 1 topic(s)." == message for message in persisted)
    assert any("marked the current topic cluster as complete" in message for message in persisted)
    assert any("Finished digestion with 1 skill file(s)." == message for message in persisted)
    assert any("Generated " in message and "architecture.md" in message for message in persisted)


class ManyTopicProvider(LLMProvider):
    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        chunk = request.chunk_batch[0]
        batch_number = request.batch_number
        return DigestDecision(
            topic_updates=[
                TopicDigest(
                    slug="skill-{batch}".format(batch=batch_number),
                    title="Skill {batch}".format(batch=batch_number),
                    summary="Summary for chunk {batch}.".format(batch=batch_number),
                    key_points=["Point {batch}".format(batch=batch_number)],
                    references=[chunk.source_ref],
                )
            ],
            should_continue=False,
            rationale="This section-like skill is complete.",
        )


def test_document_digester_keeps_all_discovered_topics_for_export(tmp_path: Path) -> None:
    input_path = tmp_path / "skills.txt"
    input_path.write_text(
        "Section one.\n\nSection two.\n\nSection three.",
        encoding="utf-8",
    )
    output_dir = tmp_path / "out"

    result = DocumentDigester(
        provider=ManyTopicProvider(),
        config=DigestConfig(max_chunk_chars=20, batch_size=1, max_active_topics=1),
    ).digest_paths([input_path], output_dir)

    assert len(result.topics) == 3
    assert [topic.slug for topic in result.topics] == ["skill-1", "skill-2", "skill-3"]
    assert (output_dir / "skill-1.md").exists()
    assert (output_dir / "skill-2.md").exists()
    assert (output_dir / "skill-3.md").exists()


class LimitedBatchProvider(LLMProvider):
    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        chunk = request.chunk_batch[0]
        return DigestDecision(
            topic_updates=[
                TopicDigest(
                    slug=chunk.chunk_id,
                    title=chunk.chunk_id,
                    summary="Summary",
                    key_points=["Point"],
                    references=[chunk.source_ref],
                )
            ],
            should_continue=True,
            rationale="Need more context.",
        )


def test_document_digester_reports_max_batches_limit(tmp_path: Path) -> None:
    input_path = tmp_path / "source.txt"
    input_path.write_text(
        "One.\n\nTwo.\n\nThree.",
        encoding="utf-8",
    )

    result = DocumentDigester(
        provider=LimitedBatchProvider(),
        config=DigestConfig(max_chunk_chars=8, batch_size=1, max_batches=2),
    ).digest_paths([input_path], tmp_path / "out")

    assert result.stop_reason == "Reached max_batches before processing all available chunks."
