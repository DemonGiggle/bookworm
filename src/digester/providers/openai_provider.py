from __future__ import annotations

import json
from typing import Dict, List, Optional

from ..core.models import DigestBatchRequest, DigestDecision, SourceRef, TopicDigest
from ..core.prompts import (
    build_digest_system_prompt,
    build_digest_user_prompt,
    build_finalize_system_prompt,
    build_finalize_user_prompt,
)
from .base import LLMProvider


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
        return DigestDecision.from_payload(payload, fallback_refs=fallback_refs)

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        if not topics:
            return []
        payload = self._complete_json(
            system_prompt=build_finalize_system_prompt(),
            user_prompt=build_finalize_user_prompt(topics),
        )
        finalized = payload.get("topics", [])
        if not isinstance(finalized, list):
            return topics
        result: List[TopicDigest] = []
        for raw_topic in finalized:
            if not isinstance(raw_topic, dict):
                continue
            refs = []
            for raw_ref in raw_topic.get("references", []):
                if not isinstance(raw_ref, dict):
                    continue
                source_id = str(raw_ref.get("source_id", "")).strip()
                source_path = str(raw_ref.get("source_path", "")).strip()
                locator = str(raw_ref.get("locator", "")).strip()
                if source_id and source_path and locator:
                    refs.append(SourceRef(source_id=source_id, source_path=source_path, locator=locator))
            result.append(
                TopicDigest(
                    slug=str(raw_topic.get("slug", "")).strip(),
                    title=str(raw_topic.get("title", "")).strip(),
                    summary=str(raw_topic.get("summary", "")).strip(),
                    key_points=[str(point).strip() for point in raw_topic.get("key_points", []) if str(point).strip()],
                    references=refs,
                )
            )
        return [topic for topic in result if topic.slug and topic.title] or topics
