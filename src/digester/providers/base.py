from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional

from ..core.models import DigestBatchRequest, DigestDecision, TopicDigest
from ..utils.progress import NoOpProgressReporter, ProgressReporter


def _escaped_preview(text: str, head_chars: int = 160, tail_chars: int = 80) -> str:
    escaped = (
        text.replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    if len(text) <= head_chars + tail_chars:
        return escaped
    head = (
        text[:head_chars]
        .replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    tail = (
        text[-tail_chars:]
        .replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    omitted = len(text) - head_chars - tail_chars
    return "{head}...[omitted {omitted} chars]...{tail}".format(
        head=head,
        omitted=omitted,
        tail=tail,
    )


class LLMProvider(ABC):
    def __init__(self, progress_reporter: Optional[ProgressReporter] = None) -> None:
        self.progress_reporter = progress_reporter or NoOpProgressReporter()

    def set_progress_reporter(self, progress_reporter: Optional[ProgressReporter]) -> None:
        self.progress_reporter = progress_reporter or NoOpProgressReporter()

    def _log_request(self, provider_name: str, model: str, system_prompt: str, user_prompt: str) -> None:
        system_chars = len(system_prompt)
        user_chars = len(user_prompt)
        total_chars = system_chars + user_chars
        self.progress_reporter.verbose(
            "Verbose: sending {total} chars to {provider} model {model} "
            "(system={system}, user={user}).".format(
                total=total_chars,
                provider=provider_name,
                model=model,
                system=system_chars,
                user=user_chars,
            )
        )
        self.progress_reporter.verbose(
            'Verbose: request preview: system="{system}" user="{user}"'.format(
                system=_escaped_preview(system_prompt),
                user=_escaped_preview(user_prompt),
            )
        )

    def _log_response(
        self,
        provider_name: str,
        model: str,
        response_text: str,
        elapsed_seconds: float,
    ) -> None:
        self.progress_reporter.verbose(
            "Verbose: {provider} model {model} returned {count} chars in {elapsed:.2f}s.".format(
                provider=provider_name,
                model=model,
                count=len(response_text),
                elapsed=elapsed_seconds,
            )
        )
        self.progress_reporter.verbose(
            'Verbose: response preview: "{preview}"'.format(
                preview=_escaped_preview(response_text),
            )
        )

    def validate_configuration(self) -> None:
        return None

    @abstractmethod
    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        raise NotImplementedError

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        return topics
