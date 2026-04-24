from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List

from ..core.models import DigestBatchRequest, DigestDecision, TopicDigest


class LLMProvider(ABC):
    @abstractmethod
    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        raise NotImplementedError

    def finalize_topics(self, topics: List[TopicDigest]) -> List[TopicDigest]:
        return topics
