from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Union

from ..core import DigestConfig, DigestOrchestrator, DigestResult, MarkdownArtifactWriter
from ..providers.base import LLMProvider
from ..sources.registry import SourceRegistry
from ..utils.progress import NoOpProgressReporter, ProgressReporter


class DocumentDigester:
    def __init__(
        self,
        provider: LLMProvider,
        config: Optional[DigestConfig] = None,
        registry: Optional[SourceRegistry] = None,
        artifact_writer: Optional[MarkdownArtifactWriter] = None,
        progress_reporter: Optional[ProgressReporter] = None,
    ) -> None:
        self.provider = provider
        self.config = config or DigestConfig()
        self.registry = registry or SourceRegistry()
        self.artifact_writer = artifact_writer or MarkdownArtifactWriter()
        self.progress_reporter = progress_reporter or NoOpProgressReporter()

    def digest_paths(self, paths: Sequence[Union[str, Path]], output_dir: Union[str, Path]) -> DigestResult:
        normalized_paths = [Path(path).resolve() for path in paths]
        output_path = Path(output_dir).resolve()
        self.progress_reporter.persist(
            "Starting digestion for {count} input path(s).".format(count=len(normalized_paths))
        )
        documents = self.registry.load_paths(
            normalized_paths,
            progress_reporter=self.progress_reporter,
        )
        result = DigestOrchestrator(
            provider=self.provider,
            config=self.config,
            progress_reporter=self.progress_reporter,
        ).run(documents)
        self.artifact_writer.write(
            result,
            output_path,
            progress_reporter=self.progress_reporter,
        )
        self.progress_reporter.persist(
            "Finished digestion with {count} skill/topic file(s).".format(count=len(result.topics))
        )
        self.progress_reporter.clear()
        return result
