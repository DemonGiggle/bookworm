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

    def _complete_json(self, system_prompt: str, user_prompt: str) -> Dict[str, object]:
        client = self._client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            response_format={"type": "json_object"},
        )
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
