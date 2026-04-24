from __future__ import annotations

import json
from typing import Sequence

from .models import DigestBatchRequest, TopicDigest


def build_digest_system_prompt() -> str:
    return (
        "You are a document digestion engine. Read the supplied chunks, update a topic-centric view of the corpus, "
        "and decide whether processing should continue. Prefer concise, reusable knowledge for downstream LLM agents. "
        "Do not restate raw text when a shorter durable abstraction is possible. "
        "Return strict JSON with keys: topic_updates, should_continue, rationale. "
        "Each topic update must include slug, title, summary, key_points, references. "
        "references must contain source_id, source_path, locator. "
        "Set should_continue to false only when the current topics already provide strong coverage for the visible corpus."
    )


def build_digest_user_prompt(request: DigestBatchRequest) -> str:
    current_topics = [
        {
            "slug": topic.slug,
            "title": topic.title,
            "summary": topic.summary,
            "key_points": topic.key_points,
            "references": [ref.render() for ref in topic.references],
        }
        for topic in request.current_topics
    ]
    batch_payload = [
        {
            "chunk_id": chunk.chunk_id,
            "source_path": chunk.source_path,
            "section_heading": chunk.section_heading,
            "locator": chunk.source_ref.locator,
            "text": chunk.text,
        }
        for chunk in request.chunk_batch
    ]
    return (
        "Digest batch {batch}/{total}.\n"
        "Current topics:\n{topics}\n\n"
        "New chunks:\n{chunks}\n\n"
        "Constraints:\n"
        "- Keep at most {max_topics} durable topics.\n"
        "- Summaries should be short and composable.\n"
        "- Key points should be fact-like and useful to another LLM.\n"
        "- Merge overlapping ideas instead of creating duplicates."
    ).format(
        batch=request.batch_number,
        total=request.total_batches,
        topics=json.dumps(current_topics, indent=2),
        chunks=json.dumps(batch_payload, indent=2),
        max_topics=request.config.max_topics,
    )


def build_finalize_system_prompt() -> str:
    return (
        "You are preparing final topic digests for markdown export. "
        "Return strict JSON with a single key named topics. "
        "Each topic must include slug, title, summary, key_points, references. "
        "Keep summaries concise, remove duplication, and preserve concrete facts."
    )


def build_finalize_user_prompt(topics: Sequence[TopicDigest]) -> str:
    payload = [
        {
            "slug": topic.slug,
            "title": topic.title,
            "summary": topic.summary,
            "key_points": topic.key_points,
            "references": [ref.render() for ref in topic.references],
        }
        for topic in topics
    ]
    return "Finalize these topics for markdown export:\n{payload}".format(
        payload=json.dumps(payload, indent=2)
    )
