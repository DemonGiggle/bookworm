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
from .schemas import (
    DIGEST_RESPONSE_SCHEMA,
    FINALIZE_RESPONSE_SCHEMA,
    schema_with_allowed_chunk_ids,
    validate_payload,
)


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: Optional[str] = None,
        organization: Optional[str] = None,
        digest_temperature: float = 0.4,
        finalize_temperature: float = 0.1,
    ) -> None:
        super().__init__()
        if not api_key:
            raise ValueError("An API key is required for hosted or compatible OpenAI clients.")
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.organization = organization
        self.digest_temperature = digest_temperature
        self.finalize_temperature = finalize_temperature

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

    def _response_format(self, schema: Dict[str, object], schema_name: str) -> Dict[str, object]:
        if self.base_url:
            return {"type": "json_object"}
        return {
            "type": "json_schema",
            "json_schema": {
                "name": schema_name,
                "strict": True,
                "schema": schema,
            },
        }

    def _request_json_completion(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        response_schema: Dict[str, object],
        schema_name: str,
    ) -> str:
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
                temperature=temperature,
                response_format=self._response_format(response_schema, schema_name),
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
        temperature: float = 0,
        response_schema: Optional[Dict[str, object]] = None,
        schema_name: str = "bookworm_response",
    ) -> Dict[str, object]:
        if response_schema is None:
            response_schema = {"type": "object"}
        content = self._request_json_completion(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            response_schema=response_schema,
            schema_name=schema_name,
        )
        try:
            payload = self._parse_json_response("OpenAI", self.model, content)
            return validate_payload(payload, response_schema, schema_name)
        except ValueError as error:
            first_error = error
        self.progress_reporter.verbose(
            (
                "Verbose: OpenAI returned invalid structured output; retrying once with a "
                "stricter JSON-only instruction and a compact schema example. Error: {error}"
            ).format(error=first_error)
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
            temperature=temperature,
            response_schema=response_schema,
            schema_name=schema_name,
        )
        retry_payload = self._parse_json_response("OpenAI", self.model, retry_content)
        return validate_payload(retry_payload, response_schema, schema_name)

    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        response_schema = schema_with_allowed_chunk_ids(
            DIGEST_RESPONSE_SCHEMA,
            "topic_updates",
            (chunk.chunk_id for chunk in request.chunk_batch),
        )
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
                        "reference_chunk_ids": ["example-source-chunk-1"],
                    }
                ],
                "should_continue": False,
                "rationale": "Example rationale.",
            },
            temperature=self.digest_temperature,
            response_schema=response_schema,
            schema_name="bookworm_digest_response",
        )
        chunk_refs = {chunk.chunk_id: chunk.source_ref for chunk in request.chunk_batch}
        return parse_digest_decision(payload, chunk_refs=chunk_refs)

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        if not topics:
            return []
        response_schema = schema_with_allowed_chunk_ids(
            FINALIZE_RESPONSE_SCHEMA,
            "topics",
            (
                chunk_id
                for topic in topics
                for chunk_id in topic.evidence_chunk_ids
            ),
        )
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
                        "reference_chunk_ids": ["example-source-chunk-1"],
                    }
                ]
            },
            temperature=self.finalize_temperature,
            response_schema=response_schema,
            schema_name="bookworm_finalize_response",
        )
        return parse_finalized_topics(payload, fallback_topics=topics)
