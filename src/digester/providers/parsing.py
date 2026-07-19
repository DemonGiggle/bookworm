from __future__ import annotations

from typing import Dict, List, Mapping, Optional, Sequence

from ..core.models import DigestDecision, SourceRef, TopicDigest, coerce_text_list


def parse_digest_decision(
    payload: Dict[str, object],
    chunk_refs: Mapping[str, SourceRef],
    chunk_texts: Optional[Mapping[str, str]] = None,
) -> DigestDecision:
    return DigestDecision.from_payload(
        payload,
        chunk_refs=dict(chunk_refs),
        chunk_texts=dict(chunk_texts or {}),
    )


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

    fallback_topics_by_slug = {
        topic.slug: topic
        for topic in fallback_topics or []
    }
    result: List[TopicDigest] = []
    for raw_topic in finalized:
        if not isinstance(raw_topic, dict):
            continue
        slug = str(raw_topic.get("slug", "")).strip()
        fallback_topic = fallback_topics_by_slug.get(slug)
        raw_chunk_ids = raw_topic.get("reference_chunk_ids")
        if raw_chunk_ids is None:
            refs = _parse_source_refs(raw_topic.get("references", []))
            chunk_ids = list(fallback_topic.evidence_chunk_ids) if fallback_topic else []
        else:
            if not isinstance(raw_chunk_ids, list):
                raise ValueError("Finalized topic reference_chunk_ids must be a list.")
            returned_chunk_ids = list(
                dict.fromkeys(
                    str(chunk_id).strip()
                    for chunk_id in raw_chunk_ids
                    if str(chunk_id).strip()
                )
            )
            allowed_ids = set(fallback_topic.evidence_chunk_ids) if fallback_topic else set()
            unknown_ids = [
                chunk_id for chunk_id in returned_chunk_ids if chunk_id not in allowed_ids
            ]
            if unknown_ids:
                raise ValueError(
                    "Finalized topic referenced unknown chunk IDs: {ids}.".format(
                        ids=", ".join(unknown_ids)
                    )
                )
            chunk_ids = list(
                dict.fromkeys(
                    list(fallback_topic.evidence_chunk_ids if fallback_topic else [])
                    + returned_chunk_ids
                )
            )
            evidence_refs = fallback_topic.evidence_refs if fallback_topic else {}
            refs = []
            for chunk_id in chunk_ids:
                ref = evidence_refs.get(chunk_id)
                if ref is not None and ref not in refs:
                    refs.append(ref)
        if raw_chunk_ids is None:
            evidence_refs = (
                dict(fallback_topic.evidence_refs) if fallback_topic else {}
            )
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
                evidence_chunk_ids=chunk_ids,
                evidence_refs={
                    chunk_id: evidence_refs[chunk_id]
                    for chunk_id in chunk_ids
                    if chunk_id in evidence_refs
                },
                evidence_texts={
                    chunk_id: fallback_topic.evidence_texts[chunk_id]
                    for chunk_id in chunk_ids
                    if fallback_topic is not None
                    and chunk_id in fallback_topic.evidence_texts
                },
            )
        )
    parsed_topics = [topic for topic in result if topic.slug and topic.title]
    if not parsed_topics:
        raise ValueError("Finalized topic payload contained no valid topics.")
    return parsed_topics
