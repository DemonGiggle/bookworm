from __future__ import annotations

import json
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


def _escaped_fragment(text: str) -> str:
    return (
        text.replace("\\", "\\\\")
        .replace("\r", "\\r")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )


def _escaped_full_text(text: str) -> str:
    return _escaped_fragment(text)


def _json_error_excerpt(text: str, position: int, radius: int = 80) -> str:
    start = max(position - radius, 0)
    end = min(position + radius, len(text))
    before = _escaped_fragment(text[start:position])
    current = text[position : position + 1]
    after = _escaped_fragment(text[position + 1 : end])
    marker = "<EOF>" if not current else _escaped_fragment(current)
    prefix = ""
    suffix = ""
    if start > 0:
        prefix = "...[{count} chars omitted]...".format(count=start)
    if end < len(text):
        suffix = "...[{count} chars omitted]...".format(count=len(text) - end)
    return '{prefix}{before}<<<HERE>>>{marker}<<<HERE>>>{after}{suffix}'.format(
        prefix=prefix,
        before=before,
        marker=marker,
        after=after,
        suffix=suffix,
    )


def _json_error_guidance(payload_label: str, position: int, text_length: int) -> str:
    if payload_label != "model response":
        return ""
    if position >= text_length:
        return (
            " The model response appears truncated before the JSON finished. "
            "Try a smaller batch or a model with stronger JSON adherence."
        )
    return (
        " The model likely added non-JSON text or broke JSON formatting. "
        "Try a smaller batch or a model with stronger JSON adherence."
    )


class LLMProvider(ABC):
    def __init__(self, progress_reporter: Optional[ProgressReporter] = None) -> None:
        self.progress_reporter = progress_reporter or NoOpProgressReporter()

    def set_progress_reporter(self, progress_reporter: Optional[ProgressReporter]) -> None:
        self.progress_reporter = progress_reporter or NoOpProgressReporter()

    def _verbosity_level(self) -> int:
        verbosity = getattr(self.progress_reporter, "verbosity", None)
        if callable(verbosity):
            return int(verbosity())
        return 0

    def _format_verbose_text(self, text: str) -> str:
        if self._verbosity_level() >= 2:
            return _escaped_full_text(text)
        return _escaped_preview(text)

    def _verbose_text_label(self) -> str:
        if self._verbosity_level() >= 2:
            return "body"
        return "preview"

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
            'Verbose: request {label}: system="{system}" user="{user}"'.format(
                label=self._verbose_text_label(),
                system=self._format_verbose_text(system_prompt),
                user=self._format_verbose_text(user_prompt),
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
            'Verbose: response {label}: "{preview}"'.format(
                label=self._verbose_text_label(),
                preview=self._format_verbose_text(response_text),
            )
        )

    def _parse_json_response(
        self,
        provider_name: str,
        model: str,
        response_text: str,
        payload_label: str = "model response",
    ) -> object:
        try:
            return json.loads(response_text)
        except json.JSONDecodeError as error:
            raise ValueError(
                "{provider} model {model} returned invalid JSON in the {payload}: {detail}. "
                "Received {count} chars. Around char {position}: \"{excerpt}\"{guidance}".format(
                    provider=provider_name,
                    model=model,
                    payload=payload_label,
                    detail=error,
                    count=len(response_text),
                    position=error.pos,
                    excerpt=_json_error_excerpt(response_text, error.pos),
                    guidance=_json_error_guidance(payload_label, error.pos, len(response_text)),
                )
            ) from error

    def validate_configuration(self) -> None:
        return None

    @abstractmethod
    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        raise NotImplementedError

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        return topics
