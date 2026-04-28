from __future__ import annotations

import json
from time import perf_counter
from typing import Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from ..core.models import DigestBatchRequest, DigestDecision, TopicDigest
from ..core.prompts import (
    build_digest_system_prompt,
    build_digest_user_prompt,
    build_finalize_system_prompt,
    build_finalize_user_prompt,
)
from .base import LLMProvider
from .parsing import parse_digest_decision, parse_finalized_topics


def _normalize_base_url(host: str, port: int) -> str:
    cleaned = host.strip()
    if not cleaned:
        cleaned = "127.0.0.1"
    if "://" not in cleaned:
        cleaned = "http://{host}".format(host=cleaned)
    parsed = urlsplit(cleaned)
    scheme = parsed.scheme or "http"
    hostname = parsed.hostname or "127.0.0.1"
    resolved_port = parsed.port or port
    return "{scheme}://{hostname}:{port}".format(
        scheme=scheme,
        hostname=hostname,
        port=resolved_port,
    )


class OllamaProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        host: str = "127.0.0.1",
        port: int = 11434,
        timeout_seconds: Optional[int] = None,
    ) -> None:
        super().__init__()
        self.model = model
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.base_url = _normalize_base_url(host=host, port=port)

    def _request_content(self, system_prompt: str, user_prompt: str) -> str:
        self._log_request("Ollama", self.model, system_prompt, user_prompt)
        payload = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            }
        ).encode("utf-8")
        request = Request(
            url="{base_url}/api/chat".format(base_url=self.base_url),
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started_at = perf_counter()
        try:
            if self.timeout_seconds is None:
                response_context = urlopen(request)
            else:
                response_context = urlopen(request, timeout=self.timeout_seconds)
            with response_context as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ValueError(
                "Ollama request failed with status {status}: {body}".format(
                    status=exc.code,
                    body=body,
                )
            )
        except URLError as exc:
            raise ValueError(
                "Unable to reach Ollama at {base_url}: {reason}".format(
                    base_url=self.base_url,
                    reason=exc.reason,
                )
            )

        response_payload = self._parse_json_response(
            "Ollama",
            self.model,
            body,
            payload_label="HTTP response body",
        )
        message = response_payload.get("message", {})
        if not isinstance(message, dict):
            raise ValueError("Ollama response did not contain a valid message payload.")
        content = str(message.get("content", "")).strip()
        if not content:
            raise ValueError("Ollama returned an empty response.")
        self._log_response("Ollama", self.model, content, perf_counter() - started_at)
        return content

    def _complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, object]:
        content = self._request_content(system_prompt=system_prompt, user_prompt=user_prompt)
        try:
            return self._parse_json_response("Ollama", self.model, content)
        except ValueError as error:
            if "invalid JSON in the model response" not in str(error):
                raise
        self.progress_reporter.verbose(
            "Verbose: Ollama returned malformed JSON; retrying once with a stricter JSON-only instruction."
        )
        retry_system_prompt = (
            "{prompt} Return only one complete JSON object with no markdown fences, no commentary, "
            "and no trailing text. Ensure every key, string, bracket, and brace is fully closed."
        ).format(prompt=system_prompt)
        retry_content = self._request_content(system_prompt=retry_system_prompt, user_prompt=user_prompt)
        return self._parse_json_response("Ollama", self.model, retry_content)

    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        payload = self._complete_json(
            system_prompt=build_digest_system_prompt(),
            user_prompt=build_digest_user_prompt(request),
        )
        fallback_refs = [chunk.source_ref for chunk in request.chunk_batch]
        return parse_digest_decision(payload, fallback_refs=fallback_refs)

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        if not topics:
            return []
        payload = self._complete_json(
            system_prompt=build_finalize_system_prompt(),
            user_prompt=build_finalize_user_prompt(topics),
        )
        return parse_finalized_topics(payload)
