from __future__ import annotations

import json
from typing import Sequence

from .models import DigestBatchRequest, TopicDigest


_TOPIC_OUTPUT_CONTRACT = (
    "Return strict JSON only. "
    "Digest responses must include topic_updates, should_continue, rationale. "
    "Finalize responses must include topics. "
    "Each topic object must include slug, title, routing_description, summary, key_points, workflow_notes, reference_chunk_ids. "
    "reference_chunk_ids must contain only chunk_id values supplied in the prompt that directly support the topic. Never copy paths or invent chunk IDs. "
    "routing_description must be a concrete when-to-use sentence for another agent; if needed, when_to_use may be used as an alias for routing_description. "
    "summary should usually be 2-5 compact paragraphs when the source supports it. "
    "key_points should usually contain 5-12 concrete bullet-style items for dense material. "
    "workflow_notes should usually contain 3-8 source-backed caveats, checks, or operator notes."
)


_TOPIC_QUALITY_GUIDANCE = (
    "Treat each topic like a section-level skill file that another agent could discover from a SKILL.md description and reuse on its own. "
    "Write summaries as markdown-ready purpose statements that explain what task the skill helps with and what context it preserves. "
    "Write key_points as actionable instructions, constraints, workflow steps, commands, or checks, not vague observations. "
    "workflow_notes must preserve caveats, validation checks, warnings, escalation hints, and source-backed operator guidance. "
    "Compress repetition, but do not compress away procedures, dependencies, sequencing, concrete implementation detail, commands, configuration values, or failure and recovery notes."
)


_ROUTING_EXAMPLE_GUIDANCE = (
    'Example routing_description values: bad="Python web framework"; '
    'good="Use this skill when setting up Flask middleware or debugging request routing." '
    'Good topic objects contain realistic summaries, concrete key_points, and grounded reference_chunk_ids instead of placeholder labels.'
)


def build_digest_system_prompt() -> str:
    return (
        "You are a document digestion engine. Read the supplied chunks, update a section-like skill map of the corpus, "
        "and decide whether the currently visible topics likely need more adjacent chunks before they are complete. Preserve high-value operational detail for downstream coding agents such as Codex, Claude Code, and Copilot, "
        "especially setup flows, hardware installation steps, wiring order, firmware or software prerequisites, commands, "
        "configuration values, validation checks, warnings, failure conditions, and recovery notes. "
        f"{_TOPIC_OUTPUT_CONTRACT} "
        f"{_TOPIC_QUALITY_GUIDANCE} "
        f"{_ROUTING_EXAMPLE_GUIDANCE} "
        "Some chunks may be image-analysis content derived from embedded document images; treat those summaries and key points as grounded evidence from the cited image location, not as speculative captions. "
        "Use should_continue=true when the visible topic still looks incomplete or likely continues in upcoming chunks. "
        "Use should_continue=false when the visible topics already have strong coverage and the next chunks are more likely to introduce different topics than extend these ones. "
        "Heuristics for should_continue=false: prefer false when most current chunks do not overlap with the active topics, or when several visible topics already look finalized and the batch is pivoting into a new area. "
        "When uncertain, prefer should_continue=true so the next adjacent batch can confirm continuity."
    )


def build_digest_user_prompt(request: DigestBatchRequest) -> str:
    current_topics = [
        {
            "slug": topic.slug,
            "title": topic.title,
            "routing_description": topic.routing_description,
            "summary": topic.summary,
            "key_points": topic.key_points,
            "workflow_notes": topic.workflow_notes,
        }
        for topic in request.current_topics
    ]
    batch_payload = [
        {
            "chunk_id": chunk.chunk_id,
            "source_path": chunk.source_path,
            "section_heading": chunk.section_heading,
            "content_kind": chunk.content_kind,
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
        "- image-analysis chunks come from embedded visuals; preserve concrete details from them when they add workflow, UI, diagram, or configuration evidence.\n"
        "- Preserve setup sequences, hardware steps, prerequisites, commands, parameter values, safety notes, verification steps, and troubleshooting clues when present.\n"
        "- Prefer operational rules, workflow steps, constraints, examples, commands, validation checks, and failure modes over generic observations.\n"
        "- Merge overlapping ideas instead of creating duplicates.\n"
        "- Return only chunk_id values from New chunks in this batch; use an empty list when no new chunk directly supports a topic. Existing evidence is retained by the application.\n"
        "- Favor detail that helps another engineer or agent reproduce the setup, understand the implementation, or avoid mistakes.\n"
        "- If a candidate topic is still thin, expand it with concrete evidence from this batch instead of returning a placeholder.\n"
        "- Use should_continue=false when the visible topics look complete and this batch is mostly pivoting into different topics; otherwise prefer true."
    ).format(
        batch=request.batch_number,
        total=request.total_batches,
        topics=json.dumps(current_topics, indent=2),
        chunks=json.dumps(batch_payload, indent=2),
        max_topics=request.config.max_active_topics,
    )


def build_finalize_system_prompt() -> str:
    return (
        "You are preparing final topic digests for markdown export as agent-readable skill files. "
        f"{_TOPIC_OUTPUT_CONTRACT} "
        f"{_TOPIC_QUALITY_GUIDANCE} "
        f"{_ROUTING_EXAMPLE_GUIDANCE} "
        "Produce rich markdown-ready summaries that keep the most useful implementation and setup detail. Each topic should read like a reusable skill file for coding agents such as Codex, Claude Code, and Copilot. "
        "Do not collapse away hardware setup flows, ordered procedures, commands, prerequisites, warnings, validation checks, or troubleshooting notes. "
        "Remove duplication, but preserve concrete facts and enough detail that another LLM or engineer could act on the output without rereading the whole source."
    )


def build_finalize_user_prompt(topics: Sequence[TopicDigest]) -> str:
    payload = [
        {
            "slug": topic.slug,
            "title": topic.title,
            "routing_description": topic.routing_description,
            "summary": topic.summary,
            "key_points": topic.key_points,
            "workflow_notes": topic.workflow_notes,
            "reference_chunk_ids": topic.evidence_chunk_ids,
        }
        for topic in topics
    ]
    return (
        "Finalize these topics for markdown export. Expand weak summaries into more useful detail where the existing topic data supports it. "
        "Make routing_description strong enough for a frontmatter description and When To Use section. "
        "Make workflow_notes capture validation checks, caveats, and source-backed operating guidance. "
        "Aim for summaries of 2-5 compact paragraphs when the source supports it, key_points with roughly 5-12 concrete items for dense topics, and workflow_notes with 3-8 grounded notes. "
        "Keep the output concise enough for downstream context windows, but detailed enough to preserve setup flow, operational nuance, and important edge cases.\n"
        "{payload}"
    ).format(payload=json.dumps(payload, indent=2))
