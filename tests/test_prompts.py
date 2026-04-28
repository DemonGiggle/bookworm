from digester.core import DigestConfig
from digester.core.models import ContentChunk, DigestBatchRequest, SourceRef, TopicDigest
from digester.core.prompts import (
    build_digest_system_prompt,
    build_digest_user_prompt,
    build_finalize_system_prompt,
    build_finalize_user_prompt,
)


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
    assert "workflow_notes" in system_prompt
    assert "setup sequences" in user_prompt
    assert "verification steps" in user_prompt
    assert "5-12 bullets" in user_prompt
    assert "active topics in view" in user_prompt
    assert "routing_description must say when another agent should load the skill" in user_prompt
    assert "operational rules" in user_prompt
    assert "later chunks may contain different topics" in user_prompt


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
            )
        ]
    )

    assert "hardware setup flows" in system_prompt
    assert "routing_description" in system_prompt
    assert "workflow_notes" in system_prompt
    assert "Expand weak summaries" in user_prompt
    assert "Make routing_description strong enough" in user_prompt
    assert "setup flow, operational nuance, and important edge cases" in user_prompt
