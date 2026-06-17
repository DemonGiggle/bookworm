from __future__ import annotations

import json
from time import perf_counter
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
        super().__init__()
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

    def _request_json_completion(self, system_prompt: str, user_prompt: str) -> str:
        client = self._client()
        self._log_request("OpenAI", self.model, system_prompt, user_prompt)
        started_at = perf_counter()
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
        self._log_response("OpenAI", self.model, content, perf_counter() - started_at)
        return content

    def _complete_json(
        self,
        system_prompt: str,
        user_prompt: str,
        retry_example_payload: Optional[Dict[str, object]] = None,
    ) -> Dict[str, object]:
        content = self._request_json_completion(system_prompt=system_prompt, user_prompt=user_prompt)
        try:
            return self._parse_json_response("OpenAI", self.model, content)
        except ValueError as error:
            if "invalid JSON in the model response" not in str(error):
                raise
        self.progress_reporter.verbose(
            "Verbose: OpenAI returned malformed JSON; retrying once with a stricter JSON-only instruction and a compact schema example."
        )
        if retry_example_payload is None:
            retry_system_prompt = (
                "{prompt} Return only one complete JSON object with no markdown fences, no commentary, "
                "and no trailing text. Ensure every key, string, bracket, and brace is fully closed."
            ).format(prompt=system_prompt)
        else:
            retry_system_prompt = self._build_retry_system_prompt(
                system_prompt=system_prompt,
                example_payload=retry_example_payload,
            )
        retry_content = self._request_json_completion(
            system_prompt=retry_system_prompt,
            user_prompt=user_prompt,
        )
        return self._parse_json_response("OpenAI", self.model, retry_content)

    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        payload = self._complete_json(
            system_prompt=build_digest_system_prompt(),
            user_prompt=build_digest_user_prompt(request),
            retry_example_payload={
                "topic_updates": [
                    {
                        "slug": "example-topic",
                        "title": "Example Topic",
                        "routing_description": "Use this skill when reviewing the example workflow.",
                        "summary": "Summarizes the example workflow and its constraints.",
                        "key_points": ["Follow the example workflow in order."],
                        "workflow_notes": ["Validate the example output before reuse."],
                        "references": [
                            {
                                "source_id": "example-source",
                                "source_path": "/tmp/example-source.txt",
                                "locator": "section 1",
                            }
                        ],
                    }
                ],
                "should_continue": False,
                "rationale": "Example rationale.",
            },
        )
        fallback_refs = [chunk.source_ref for chunk in request.chunk_batch]
        return parse_digest_decision(payload, fallback_refs=fallback_refs)

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        if not topics:
            return []
        payload = self._complete_json(
            system_prompt=build_finalize_system_prompt(),
            user_prompt=build_finalize_user_prompt(topics),
            retry_example_payload={
                "topics": [
                    {
                        "slug": "example-topic",
                        "title": "Example Topic",
                        "routing_description": "Use this skill when reviewing the finalized example workflow.",
                        "summary": "Summarizes the finalized example workflow and its constraints.",
                        "key_points": ["Follow the finalized example workflow in order."],
                        "workflow_notes": ["Validate the finalized example output before reuse."],
                        "references": [
                            {
                                "source_id": "example-source",
                                "source_path": "/tmp/example-source.txt",
                                "locator": "section 1",
                            }
                        ],
                    }
                ]
            },
        )
        return parse_finalized_topics(payload, fallback_topics=topics)
