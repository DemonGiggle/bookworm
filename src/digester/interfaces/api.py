from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence, Union

from ..core import DigestConfig, DigestOrchestrator, DigestResult, MarkdownArtifactWriter
from ..providers.base import LLMProvider
from ..sources.registry import SourceRegistry


class DocumentDigester:
    def __init__(
        self,
        provider: LLMProvider,
        config: Optional[DigestConfig] = None,
        registry: Optional[SourceRegistry] = None,
        artifact_writer: Optional[MarkdownArtifactWriter] = None,
    ) -> None:
        self.provider = provider
        self.config = config or DigestConfig()
        self.registry = registry or SourceRegistry()
        self.artifact_writer = artifact_writer or MarkdownArtifactWriter()

    def digest_paths(self, paths: Sequence[Union[str, Path]], output_dir: Union[str, Path]) -> DigestResult:
        normalized_paths = [Path(path).resolve() for path in paths]
        documents = self.registry.load_paths(normalized_paths)
        result = DigestOrchestrator(provider=self.provider, config=self.config).run(documents)
        self.artifact_writer.write(result, Path(output_dir).resolve())
        return result
