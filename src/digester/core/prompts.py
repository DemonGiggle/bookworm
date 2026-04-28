from __future__ import annotations

import json
from typing import Sequence

from .models import DigestBatchRequest, TopicDigest


def build_digest_system_prompt() -> str:
    return (
        "You are a document digestion engine. Read the supplied chunks, update a section-like skill map of the corpus, "
        "and decide whether the currently visible topics likely need more adjacent chunks before they are complete. Preserve high-value operational detail for downstream coding agents such as Codex, Claude Code, and Copilot, "
        "especially setup flows, hardware installation steps, wiring order, firmware or software prerequisites, commands, "
        "configuration values, validation checks, warnings, failure conditions, and recovery notes. "
        "Compress repetition, but do not compress away procedures, dependencies, sequencing, or concrete implementation detail. "
        "Return strict JSON with keys: topic_updates, should_continue, rationale. "
        "Each topic update must include slug, title, routing_description, summary, key_points, workflow_notes, references. "
        "references must contain source_id, source_path, locator. "
        "Treat each topic like a section-level skill file that another agent could discover from a SKILL.md description and reuse on its own. "
        "routing_description must explicitly say when another agent should load the skill. "
        "Write summaries as markdown-ready purpose statements that explain what task the skill helps with and what context it preserves. "
        "Write key_points as actionable instructions, constraints, workflow steps, commands, or checks, not vague observations. "
        "workflow_notes must preserve caveats, validation checks, warnings, and source-backed operator guidance. "
        "Set should_continue to false only when the current visible topics already have strong coverage and the next chunks are more likely to introduce different topics than extend these ones."
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
        "- Topics should behave like section-level skill files for coding agents: each one should cover a coherent, reusable slice of the source rather than the whole corpus.\n"
        "- routing_description must say when another agent should load the skill, without copying the title.\n"
        "- Summaries should be rich, actionable, and markdown-ready, usually 2-5 compact paragraphs when the material supports it.\n"
        "- Preserve setup sequences, hardware steps, prerequisites, commands, parameter values, safety notes, verification steps, and troubleshooting clues when present.\n"
        "- Key points should be concrete, imperative when useful, and numerous enough to preserve important detail; prefer roughly 5-12 bullets when the source is dense.\n"
        "- workflow_notes should preserve validation checks, caveats, escalation hints, and source-backed usage notes.\n"
        "- Prefer operational rules, workflow steps, constraints, examples, commands, validation checks, and failure modes over generic observations.\n"
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
        "You are preparing final topic digests for markdown export as agent-readable skill files. "
        "Return strict JSON with a single key named topics. "
        "Each topic must include slug, title, routing_description, summary, key_points, workflow_notes, references. "
        "Produce rich markdown-ready summaries that keep the most useful implementation and setup detail. Each topic should read like a reusable skill file for coding agents such as Codex, Claude Code, and Copilot. "
        "routing_description must be explicit enough to drive frontmatter description and a When To Use section without inferring it from the summary. "
        "Key points must be actionable instructions, constraints, ordered workflow guidance, examples, commands, or checks. "
        "workflow_notes must preserve validation checks, warnings, caveats, and source-backed operating guidance. "
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
            "references": [ref.render() for ref in topic.references],
        }
        for topic in topics
    ]
    return (
        "Finalize these topics for markdown export. Expand weak summaries into more useful detail where the existing topic data supports it. "
        "Make routing_description strong enough for a frontmatter description and When To Use section. "
        "Make workflow_notes capture validation checks, caveats, and source-backed operating guidance. "
        "Keep the output concise enough for downstream context windows, but detailed enough to preserve setup flow, operational nuance, and important edge cases.\n"
        "{payload}"
    ).format(payload=json.dumps(payload, indent=2))
