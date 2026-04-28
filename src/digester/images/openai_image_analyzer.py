from __future__ import annotations

import base64
import json
from time import perf_counter
from typing import Dict, List, Optional

from ..core.models import EmbeddedImage, ImageAnalysis
from ..providers.openai_provider import OpenAIProvider
from .base import ImageAnalyzer


def _build_image_system_prompt() -> str:
    return (
        "You analyze embedded document images for a document digestion pipeline. "
        "Return strict JSON with keys: summary, key_points. "
        "Describe only details that are visible in the image or grounded by the supplied nearby document context. "
        "Preserve operationally useful information such as UI text, commands, diagrams, labels, configuration values, warnings, or workflow order when present. "
        "Do not invent unreadable details."
    )


def _build_image_user_prompt(image: EmbeddedImage) -> str:
    payload = {
        "source_path": image.source_ref.source_path,
        "locator": image.source_ref.locator,
        "filename": image.filename,
        "mime_type": image.mime_type,
        "caption": image.caption,
        "context_text": image.context_text,
    }
    return "Analyze this embedded image and summarize only grounded details.\n{payload}".format(
        payload=json.dumps(payload, indent=2),
    )


def _data_url(image: EmbeddedImage) -> str:
    encoded = base64.b64encode(image.data).decode("ascii")
    return "data:{mime_type};base64,{encoded}".format(
        mime_type=image.mime_type or "application/octet-stream",
        encoded=encoded,
    )


def _parse_image_analysis(payload: Dict[str, object]) -> ImageAnalysis:
    summary = str(payload.get("summary", "")).strip()
    if not summary:
        raise ValueError("Image analyzer returned an empty summary.")
    raw_key_points = payload.get("key_points", [])
    key_points = [
        str(point).strip()
        for point in raw_key_points
        if str(point).strip()
    ] if isinstance(raw_key_points, list) else []
    return ImageAnalysis(summary=summary, key_points=key_points)


class OpenAIImageAnalyzer(ImageAnalyzer):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
    ) -> None:
        super().__init__()
        self.model = model
        self._client_provider = OpenAIProvider(
            model=model,
            api_key=api_key,
            base_url=base_url,
            organization=organization,
        )

    def set_progress_reporter(self, progress_reporter) -> None:
        super().set_progress_reporter(progress_reporter)
        self._client_provider.set_progress_reporter(progress_reporter)

    def validate_configuration(self) -> None:
        self._client_provider.validate_configuration()

    def analyze(self, image: EmbeddedImage) -> ImageAnalysis:
        system_prompt = _build_image_system_prompt()
        user_prompt = _build_image_user_prompt(image)
        client = self._client_provider._client()
        self._client_provider._log_request("OpenAI", self.model, system_prompt, user_prompt)
        started_at = perf_counter()
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": _data_url(image)}},
                        ],
                    },
                ],
                response_format={"type": "json_object"},
            )
        except Exception as error:
            self._client_provider._raise_openai_error(error)
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Image analyzer returned an empty response.")
        self._client_provider._log_response("OpenAI", self.model, content, perf_counter() - started_at)
        payload = self._client_provider._parse_json_response("OpenAI", self.model, content)
        if not isinstance(payload, dict):
            raise ValueError("Image analyzer response must be a JSON object.")
        return _parse_image_analysis(payload)
