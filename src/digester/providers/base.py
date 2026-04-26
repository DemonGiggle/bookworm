from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..core.models import DigestBatchRequest, DigestDecision, TopicDigest


class LLMProvider(ABC):
    def validate_configuration(self) -> None:
        return None

    @abstractmethod
    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        raise NotImplementedError

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        return topics
