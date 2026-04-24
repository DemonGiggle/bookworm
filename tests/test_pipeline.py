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
            summary="Summarizes the system design and interfaces.",
            key_points=["Uses adapters for ingestion", "Emits topic-centric markdown"],
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

    result = DocumentDigester(
        provider=FakeProvider(),
        config=DigestConfig(max_chunk_chars=70, batch_size=1, minimum_batches_before_stop=2),
        progress_reporter=reporter,
    ).digest_paths([input_path], output_dir)

    assert (output_dir / "architecture.md").exists()
    assert (output_dir / "INDEX.md").exists()
    assert "Architecture" in (output_dir / "INDEX.md").read_text(encoding="utf-8")
    assert result.stop_reason == "Topic coverage is sufficient after two batches."
    persisted = [message for kind, message in reporter.messages if kind == "persist"]
    assert any("Loaded source.txt with 1 section(s)." == message for message in persisted)
    assert any("Prepared 3 chunk(s) from 1 document(s)." == message for message in persisted)
    assert any("Generated " in message and "architecture.md" in message for message in persisted)
