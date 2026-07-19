from __future__ import annotations

import json
from typing import Sequence

from .models import DigestBatchRequest, TopicDigest


MAX_FINALIZE_PROMPT_CHARS = 24000
MAX_FINALIZE_SUMMARY_CHARS = 6000
MAX_FINALIZE_LIST_CHARS = 5000


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
        "and provide an advisory continuity signal for the currently visible topics. The application, not this signal alone, controls topic-cluster boundaries. Preserve high-value operational detail for downstream coding agents such as Codex, Claude Code, and Copilot, "
        "especially setup flows, hardware installation steps, wiring order, firmware or software prerequisites, commands, "
        "configuration values, validation checks, warnings, failure conditions, and recovery notes. "
        f"{_TOPIC_OUTPUT_CONTRACT} "
        f"{_TOPIC_QUALITY_GUIDANCE} "
        f"{_ROUTING_EXAMPLE_GUIDANCE} "
        "Use topic granularity suitable for a skill registry: a short single-source, single-subject document should usually remain one cohesive skill, or at most two genuinely independent skills. "
        "Extend a compatible current topic instead of creating a new slug for each document section. Never emit a broad overview topic alongside narrower topics that repeat the same evidence. "
        "Split only when topics serve clearly different user intents, can stand alone, and have little content overlap. Some chunks may be image-analysis content derived from embedded document images; treat those summaries and key points as grounded evidence from the cited image location, not as speculative captions. "
        "Set should_continue only as an advisory signal: true when this batch extends active topics, false when it is internally complete or pivots away from them. Do not predict unseen chunks."
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
        "- Prefer extending Current topics. Do not map headings one-to-one into new skills.\n"
        "- For a short single-subject source, usually keep one cohesive topic; never combine an overview topic with overlapping child topics.\n"
        "- Return only chunk_id values from New chunks in this batch; use an empty list when no new chunk directly supports a topic. Existing evidence is retained by the application.\n"
        "- Favor detail that helps another engineer or agent reproduce the setup, understand the implementation, or avoid mistakes.\n"
        "- If a candidate topic is still thin, expand it with concrete evidence from this batch instead of returning a placeholder.\n"
        "- should_continue is advisory only: report whether this batch extends active topics; do not predict unseen chunks."
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
        "The evidence snippets are authoritative; treat draft topic wording only as an organizational aid. "
        "Keep a draft claim only when it can be directly verified in the supplied evidence, and remove or narrow unsupported wording. "
        "Do not invent failure effects, prohibitions, best practices, causal explanations, diagnostic conclusions, or extrapolated lifetime/capacity claims, even when they seem technically plausible. "
        "Do not silently repair ambiguous or inconsistent source wording into a new technical claim. Produce rich markdown-ready summaries that keep the most useful directly supported implementation and setup detail. Each topic should read like a reusable skill file for coding agents such as Codex, Claude Code, and Copilot. "
        "Do not collapse away hardware setup flows, ordered procedures, commands, prerequisites, warnings, validation checks, or troubleshooting notes. "
        "Preserve every supplied reference_chunk_id in the finalized topic; these IDs are the accumulated grounding for facts already present in the draft. "
        "Remove duplication, but preserve concrete facts and enough detail that another LLM or engineer could act on the output without rereading the whole source."
    )


def build_grounding_review_system_prompt() -> str:
    return (
        "You are the final grounding auditor for an agent-readable skill. "
        f"{_TOPIC_OUTPUT_CONTRACT} "
        "The evidence snippets are the only authority. Review the supplied draft sentence by sentence and return a corrected topic. "
        "Remove or narrow every statement, instruction, warning, formula, causal explanation, diagnostic conclusion, or recommendation that is not directly stated or unambiguously computable from the evidence. "
        "Do not add new advice, improve the engineering design, repair source ambiguities, or extrapolate beyond the documented example. "
        "Preserve supported operational detail and the complete supplied reference_chunk_ids. Prefer omission over a plausible unsupported claim."
    )


def _bounded_text_list(items: Sequence[str], max_chars: int) -> Sequence[str]:
    result = []
    used = 0
    for item in items:
        remaining = max_chars - used
        if remaining <= 0:
            break
        bounded = item[:remaining]
        if bounded:
            result.append(bounded)
            used += len(bounded)
    return result


def build_finalize_user_prompt(topics: Sequence[TopicDigest]) -> str:
    if len(topics) != 1:
        raise ValueError("Finalization prompts must contain exactly one topic.")
    topic = topics[0]
    if not topic.evidence_chunk_ids:
        raise ValueError(
            "Topic '{slug}' cannot be finalized without evidence chunk IDs.".format(
                slug=topic.slug
            )
        )
    missing_evidence = [
        chunk_id
        for chunk_id in topic.evidence_chunk_ids
        if not topic.evidence_texts.get(chunk_id, "").strip()
    ]
    if missing_evidence:
        raise ValueError(
            "Topic '{slug}' is missing evidence text for chunks: {ids}.".format(
                slug=topic.slug,
                ids=", ".join(missing_evidence),
            )
        )
    payload = [
        {
            "slug": topic.slug,
            "title": topic.title,
            "routing_description": topic.routing_description,
            "summary": topic.summary[:MAX_FINALIZE_SUMMARY_CHARS],
            "key_points": _bounded_text_list(topic.key_points, MAX_FINALIZE_LIST_CHARS),
            "workflow_notes": _bounded_text_list(
                topic.workflow_notes, MAX_FINALIZE_LIST_CHARS
            ),
            "reference_chunk_ids": topic.evidence_chunk_ids,
            "evidence": [],
        }
    ]
    prefix = (
        "Finalize this topic for markdown export. Refine weak wording only from the supplied facts and evidence snippets. "
        "Audit every output sentence against the evidence snippets; omit plausible advice or consequences that the evidence does not state. "
        "Make routing_description strong enough for a frontmatter description and When To Use section. "
        "Make workflow_notes capture validation checks, caveats, and source-backed operating guidance. "
        "Return the complete supplied reference_chunk_ids list; do not discard accumulated evidence while retaining draft facts. "
        "Aim for summaries of 2-5 compact paragraphs when the source supports it, key_points with roughly 5-12 concrete items for dense topics, and workflow_notes with 3-8 grounded notes. "
        "Keep the output concise enough for downstream context windows, but detailed enough to preserve setup flow, operational nuance, and important edge cases.\n"
    )
    for chunk_id in topic.evidence_chunk_ids:
        text = topic.evidence_texts.get(chunk_id, "")
        if not text:
            continue
        base_chars = len(prefix) + len(json.dumps(payload, indent=2))
        remaining = MAX_FINALIZE_PROMPT_CHARS - base_chars - 100
        if remaining <= 0:
            break
        payload[0]["evidence"].append(
            {"chunk_id": chunk_id, "text": text[:remaining]}
        )
    prompt = prefix + json.dumps(payload, indent=2)
    while len(prompt) > MAX_FINALIZE_PROMPT_CHARS and payload[0]["evidence"]:
        overflow = len(prompt) - MAX_FINALIZE_PROMPT_CHARS
        last_evidence = payload[0]["evidence"][-1]
        last_text = last_evidence["text"]
        if len(last_text) <= overflow:
            payload[0]["evidence"].pop()
        else:
            last_evidence["text"] = last_text[: len(last_text) - overflow]
        prompt = prefix + json.dumps(payload, indent=2)
    if len(prompt) > MAX_FINALIZE_PROMPT_CHARS:
        raise ValueError("Finalization prompt exceeded its hard character budget.")
    return prompt
