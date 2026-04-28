from __future__ import annotations

import base64
import json
from time import perf_counter
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ..core.models import EmbeddedImage, ImageAnalysis
from ..providers.base import LLMProvider
from ..providers.ollama_provider import _normalize_base_url
from .base import ImageAnalyzer
from .openai_image_analyzer import (
    _build_image_system_prompt,
    _build_image_user_prompt,
    _parse_image_analysis,
)


class _ImageLogHelper(LLMProvider):
    def digest_batch(self, request):
        raise NotImplementedError


class OllamaImageAnalyzer(ImageAnalyzer):
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
        self._log_helper = _ImageLogHelper()

    def set_progress_reporter(self, progress_reporter) -> None:
        super().set_progress_reporter(progress_reporter)
        self._log_helper.set_progress_reporter(progress_reporter)

    def analyze(self, image: EmbeddedImage) -> ImageAnalysis:
        system_prompt = _build_image_system_prompt()
        user_prompt = _build_image_user_prompt(image)
        self._log_helper._log_request("Ollama image analyzer", self.model, system_prompt, user_prompt)
        payload = json.dumps(
            {
                "model": self.model,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0},
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt,
                        "images": [base64.b64encode(image.data).decode("ascii")],
                    },
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
                "Ollama image analysis failed with status {status}: {body}".format(
                    status=exc.code,
                    body=body,
                )
            ) from exc
        except URLError as exc:
            raise ValueError(
                "Unable to reach Ollama image analyzer at {base_url}: {reason}".format(
                    base_url=self.base_url,
                    reason=exc.reason,
                )
            ) from exc

        response_payload = self._log_helper._parse_json_response(
            "Ollama image analyzer",
            self.model,
            body,
            payload_label="HTTP response body",
        )
        if not isinstance(response_payload, dict):
            raise ValueError("Ollama image analyzer returned an invalid HTTP response body.")
        message = response_payload.get("message", {})
        if not isinstance(message, dict):
            raise ValueError("Ollama image analyzer response did not contain a valid message payload.")
        content = str(message.get("content", "")).strip()
        if not content:
            raise ValueError("Ollama image analyzer returned an empty response.")
        self._log_helper._log_response(
            "Ollama image analyzer",
            self.model,
            content,
            perf_counter() - started_at,
        )
        analysis_payload = self._log_helper._parse_json_response(
            "Ollama image analyzer",
            self.model,
            content,
        )
        if not isinstance(analysis_payload, dict):
            raise ValueError("Ollama image analyzer response must be a JSON object.")
        return _parse_image_analysis(analysis_payload)
