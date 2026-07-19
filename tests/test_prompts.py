import json

import pytest

from digester.core import DigestConfig
from digester.core.models import ContentChunk, DigestBatchRequest, SourceRef, TopicDigest
from digester.core.prompts import (
    MAX_FINALIZE_PROMPT_CHARS,
    build_digest_system_prompt,
    build_digest_user_prompt,
    build_finalize_system_prompt,
    build_finalize_user_prompt,
)
from digester.images.openai_image_analyzer import _build_image_system_prompt


def test_digest_prompts_preserve_setup_and_hardware_detail() -> None:
    system_prompt = build_digest_system_prompt()
    request = DigestBatchRequest(
        config=DigestConfig(max_active_topics=8),
        batch_number=1,
        total_batches=3,
        chunk_batch=[
            ContentChunk(
                chunk_id="chunk-1",
                source_id="board-guide",
                source_path="/tmp/board-guide.txt",
                section_heading="Hardware setup",
                text="Connect power, attach the ribbon cable, flash firmware, and validate LEDs.",
                source_ref=SourceRef(
                    source_id="board-guide",
                    source_path="/tmp/board-guide.txt",
                    locator="page 1",
                ),
            )
        ],
        current_topics=[],
    )
    user_prompt = build_digest_user_prompt(request)

    assert "hardware installation steps" in system_prompt
    assert "section-level skill file" in system_prompt
    assert "Codex, Claude Code, and Copilot" in system_prompt
    assert "SKILL.md description" in system_prompt
    assert "routing_description" in system_prompt
    assert "when_to_use may be used as an alias" in system_prompt
    assert "workflow_notes" in system_prompt
    assert 'bad="Python web framework"' in system_prompt
    assert 'good="Use this skill when setting up Flask middleware or debugging request routing."' in system_prompt
    assert "application, not this signal alone" in system_prompt
    assert "Do not predict unseen chunks" in system_prompt
    assert "setup sequences" in user_prompt
    assert "verification steps" in user_prompt
    assert "active topics in view" in user_prompt
    assert "operational rules" in user_prompt
    assert "expand it with concrete evidence from this batch" in user_prompt
    assert "should_continue is advisory only" in user_prompt


def test_finalize_prompts_request_richer_markdown_ready_output() -> None:
    system_prompt = build_finalize_system_prompt()
    user_prompt = build_finalize_user_prompt(
        [
            TopicDigest(
                slug="hardware-setup",
                title="Hardware setup",
                routing_description="Use this skill when bringing the hardware setup online.",
                summary="Short summary",
                key_points=["Attach the board"],
                workflow_notes=["Validate the LED state before moving on."],
                references=[
                    SourceRef(
                        source_id="setup-guide",
                        source_path="/tmp/setup-guide.txt",
                        locator="section 2",
                    )
                ],
                evidence_chunk_ids=["setup-guide-chunk-1"],
                evidence_texts={
                    "setup-guide-chunk-1": "Attach the board, then validate the LED state."
                },
            )
        ]
    )

    assert "hardware setup flows" in system_prompt
    assert "routing_description" in system_prompt
    assert "workflow_notes" in system_prompt
    assert "when_to_use may be used as an alias" in system_prompt
    assert 'good="Use this skill when setting up Flask middleware or debugging request routing."' in system_prompt
    assert "Refine weak wording only from the supplied facts" in user_prompt
    assert "Make routing_description strong enough" in user_prompt
    assert "workflow_notes with 3-8 grounded notes" in user_prompt
    assert "setup flow, operational nuance, and important edge cases" in user_prompt
    assert '"reference_chunk_ids": [\n      "setup-guide-chunk-1"' in user_prompt
    assert "Return the complete supplied reference_chunk_ids list" in user_prompt
    assert '"source_path": "/tmp/setup-guide.txt"' not in user_prompt
    assert '"locator": "section 2"' not in user_prompt
    payload = json.loads(user_prompt[user_prompt.index("[") :])
    assert payload[0]["reference_chunk_ids"] == ["setup-guide-chunk-1"]
    assert payload[0]["evidence"] == [
        {
            "chunk_id": "setup-guide-chunk-1",
            "text": "Attach the board, then validate the LED state.",
        }
    ]


def test_finalize_prompt_is_bounded_for_large_topic_and_evidence() -> None:
    topic = TopicDigest(
        slug="large-topic",
        title="Large Topic",
        routing_description="Use this skill when reviewing a large evidence set.",
        summary="S" * 50000,
        key_points=["K" * 5000 for _ in range(20)],
        workflow_notes=["W" * 5000 for _ in range(20)],
        evidence_chunk_ids=["chunk-{index}".format(index=index) for index in range(20)],
        evidence_texts={
            "chunk-{index}".format(index=index): "E" * 10000
            for index in range(20)
        },
    )

    prompt = build_finalize_user_prompt([topic])

    assert len(prompt) <= MAX_FINALIZE_PROMPT_CHARS
    assert '"chunk_id": "chunk-0"' in prompt


def test_finalize_prompt_rejects_missing_evidence_text() -> None:
    topic = TopicDigest(
        slug="missing-evidence",
        title="Missing Evidence",
        routing_description="Use this skill when testing missing evidence handling.",
        summary="Summary.",
        evidence_chunk_ids=["chunk-1"],
    )

    with pytest.raises(ValueError, match="missing evidence text"):
        build_finalize_user_prompt([topic])


def test_image_prompt_requests_type_specific_grounded_detail() -> None:
    system_prompt = _build_image_system_prompt()

    assert "diagram or flowchart" in system_prompt
    assert "UI screenshot" in system_prompt
    assert "table or chart" in system_prompt
    assert "photo" in system_prompt
    assert "Do not invent unreadable details." in system_prompt
