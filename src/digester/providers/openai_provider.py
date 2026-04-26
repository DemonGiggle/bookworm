from __future__ import annotations

import json
from typing import Dict, List, Optional

from ..core.models import DigestBatchRequest, DigestDecision, TopicDigest
from ..core.prompts import (
    build_digest_system_prompt,
    build_digest_user_prompt,
    build_finalize_system_prompt,
    build_finalize_user_prompt,
)
from .base import LLMProvider
from .parsing import parse_digest_decision, parse_finalized_topics


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
    ) -> None:
        if not api_key:
            raise ValueError("An API key is required for hosted or compatible OpenAI clients.")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.organization = organization

    def _client(self):
        from openai import OpenAI

        return OpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
            organization=self.organization,
        )

    def _raise_openai_error(self, error: Exception) -> None:
        from openai import (
            APIConnectionError,
            APITimeoutError,
            AuthenticationError,
            BadRequestError,
            NotFoundError,
            PermissionDeniedError,
            RateLimitError,
        )

        detail = str(error)
        body = getattr(error, "body", None)
        error_payload = body.get("error", {}) if isinstance(body, dict) else {}
        error_message = error_payload.get("message", "")
        error_code = error_payload.get("code", "")
        if isinstance(error, AuthenticationError):
            raise ValueError(
                "OpenAI authentication failed. Check the API key and organization settings."
            ) from error
        if isinstance(error, PermissionDeniedError):
            if (
                "does not have access to model" in detail
                or "does not have access to model" in error_message
                or error_code == "model_not_found"
            ):
                raise ValueError(
                    "OpenAI project does not have access to model {model}. "
                    "Choose a model enabled for this project or use a different API key."
                    .format(model=self.model)
                ) from error
            raise ValueError(
                "OpenAI denied access while using model {model}: {detail}".format(
                    model=self.model,
                    detail=detail,
                )
            ) from error
        if isinstance(error, NotFoundError):
            raise ValueError(
                "OpenAI could not find model {model}. Check the model name and project access."
                .format(model=self.model)
            ) from error
        if isinstance(error, BadRequestError):
            raise ValueError(
                "OpenAI rejected the request for model {model}: {detail}".format(
                    model=self.model,
                    detail=detail,
                )
            ) from error
        if isinstance(error, RateLimitError):
            raise ValueError(
                "OpenAI rate limited requests for model {model}: {detail}".format(
                    model=self.model,
                    detail=detail,
                )
            ) from error
        if isinstance(error, (APIConnectionError, APITimeoutError)):
            raise ValueError(
                "Unable to reach OpenAI for model {model}: {detail}".format(
                    model=self.model,
                    detail=detail,
                )
            ) from error
        raise error

    def validate_configuration(self) -> None:
        client = self._client()
        try:
            client.models.retrieve(self.model)
        except Exception as error:
            self._raise_openai_error(error)

    def _complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, object]:
        client = self._client()
        try:
            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
            )
        except Exception as error:
            self._raise_openai_error(error)
        content = response.choices[0].message.content
        if not content:
            raise ValueError("Model returned an empty response.")
        return json.loads(content)

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
        return parse_finalized_topics(payload, fallback_topics=topics)
