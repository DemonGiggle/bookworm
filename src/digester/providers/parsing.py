from __future__ import annotations

from typing import Dict, List, Optional, Sequence

from ..core.models import DigestDecision, SourceRef, TopicDigest, coerce_text_list


def parse_digest_decision(
    payload: Dict[str, object],
    fallback_refs: Sequence[SourceRef],
) -> DigestDecision:
    return DigestDecision.from_payload(payload, fallback_refs=fallback_refs)


def _parse_source_refs(raw_refs: object) -> List[SourceRef]:
    refs = []
    if not isinstance(raw_refs, list):
        return refs
    for raw_ref in raw_refs:
        if not isinstance(raw_ref, dict):
            continue
        source_id = str(raw_ref.get("source_id", "")).strip()
        source_path = str(raw_ref.get("source_path", "")).strip()
        locator = str(raw_ref.get("locator", "")).strip()
        if source_id and source_path and locator:
            refs.append(SourceRef(source_id=source_id, source_path=source_path, locator=locator))
    return refs


def parse_finalized_topics(
    payload: Dict[str, object],
    fallback_topics: Optional[Sequence[TopicDigest]] = None,
) -> List[TopicDigest]:
    finalized = payload.get("topics")
    if not isinstance(finalized, list):
        raise ValueError("Finalized topic payload must contain a topics list.")

    fallback_refs_by_slug = {
        topic.slug: list(topic.references)
        for topic in fallback_topics or []
    }
    result: List[TopicDigest] = []
    for raw_topic in finalized:
        if not isinstance(raw_topic, dict):
            continue
        slug = str(raw_topic.get("slug", "")).strip()
        refs = _parse_source_refs(raw_topic.get("references", []))
        if not refs:
            refs = fallback_refs_by_slug.get(slug, [])
        result.append(
            TopicDigest(
                slug=slug,
                title=str(raw_topic.get("title", "")).strip(),
                routing_description=str(
                    raw_topic.get("routing_description") or raw_topic.get("when_to_use") or ""
                ).strip(),
                summary=str(raw_topic.get("summary", "")).strip(),
                key_points=coerce_text_list(raw_topic.get("key_points", [])),
                workflow_notes=coerce_text_list(raw_topic.get("workflow_notes", [])),
                references=refs,
            )
        )
    parsed_topics = [topic for topic in result if topic.slug and topic.title]
    if not parsed_topics:
        raise ValueError("Finalized topic payload contained no valid topics.")
    return parsed_topics
