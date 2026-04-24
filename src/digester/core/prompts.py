from __future__ import annotations

import json
from typing import Sequence

from .models import DigestBatchRequest, TopicDigest


def build_digest_system_prompt() -> str:
    return (
        "You are a document digestion engine. Read the supplied chunks, update a section-like skill map of the corpus, "
        "and decide whether the currently visible topics likely need more adjacent chunks before they are complete. Preserve high-value operational detail for downstream LLM agents, "
        "especially setup flows, hardware installation steps, wiring order, firmware or software prerequisites, commands, "
        "configuration values, validation checks, warnings, failure conditions, and recovery notes. "
        "Compress repetition, but do not compress away procedures, dependencies, sequencing, or concrete implementation detail. "
        "Return strict JSON with keys: topic_updates, should_continue, rationale. "
        "Each topic update must include slug, title, summary, key_points, references. "
        "references must contain source_id, source_path, locator. "
        "Treat each topic like a section-level skill file that another agent could reuse on its own. "
        "Set should_continue to false only when the current visible topics already have strong coverage and the next chunks are more likely to introduce different topics than extend these ones."
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
        "- Keep at most {max_topics} active topics in view for this batch.\n"
        "- Topics should behave like section-level skill files: each one should cover a coherent, reusable slice of the source rather than the whole corpus.\n"
        "- Summaries should be rich, actionable, and markdown-ready, usually 2-5 compact paragraphs when the material supports it.\n"
        "- Preserve setup sequences, hardware steps, prerequisites, commands, parameter values, safety notes, verification steps, and troubleshooting clues when present.\n"
        "- Key points should be concrete, fact-like, and numerous enough to preserve important detail; prefer roughly 5-12 bullets when the source is dense.\n"
        "- Merge overlapping ideas instead of creating duplicates.\n"
        "- Favor detail that helps another engineer or agent reproduce the setup, understand the implementation, or avoid mistakes.\n"
        "- Use should_continue=true when the visible topic still looks incomplete or likely continues in upcoming chunks. Use should_continue=false when these visible topics look complete even if later chunks may contain different topics."
    ).format(
        batch=request.batch_number,
        total=request.total_batches,
        topics=json.dumps(current_topics, indent=2),
        chunks=json.dumps(batch_payload, indent=2),
        max_topics=request.config.max_active_topics,
    )


def build_finalize_system_prompt() -> str:
    return (
        "You are preparing final topic digests for markdown export. "
        "Return strict JSON with a single key named topics. "
        "Each topic must include slug, title, summary, key_points, references. "
        "Produce rich markdown-ready summaries that keep the most useful implementation and setup detail. Each topic should read like a reusable skill file for another agent. "
        "Do not collapse away hardware setup flows, ordered procedures, commands, prerequisites, warnings, validation checks, or troubleshooting notes. "
        "Remove duplication, but preserve concrete facts and enough detail that another LLM or engineer could act on the output without rereading the whole source."
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
    return (
        "Finalize these topics for markdown export. Expand weak summaries into more useful detail where the existing topic data supports it. "
        "Keep the output concise enough for downstream context windows, but detailed enough to preserve setup flow, operational nuance, and important edge cases.\n"
        "{payload}"
    ).format(payload=json.dumps(payload, indent=2))
