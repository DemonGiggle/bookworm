from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional

from ..utils.progress import NoOpProgressReporter, ProgressReporter, file_label
from .models import DigestResult, TopicDigest


def _unique_source_paths(topic: TopicDigest):
    seen = set()
    ordered = []
    for ref in topic.references:
        if ref.source_path in seen:
            continue
        seen.add(ref.source_path)
        ordered.append(ref.source_path)
    return ordered


def _render_topic_markdown(topic: TopicDigest) -> str:
    lines = [
        "# {title}".format(title=topic.title),
        "",
        "## Overview",
        "",
        topic.summary.strip(),
        "",
        "## Detailed takeaways",
        "",
    ]
    lines.extend("- {point}".format(point=point) for point in topic.key_points)
    source_paths = _unique_source_paths(topic)
    if source_paths:
        lines.extend(["", "## Source files", ""])
        lines.extend("- `{path}`".format(path=path) for path in source_paths)
    lines.extend(["", "## Source references", ""])
    lines.extend("- {ref}".format(ref=ref.render()) for ref in topic.references)
    lines.append("")
    return "\n".join(lines)


def _render_index_markdown(result: DigestResult) -> str:
    lines = [
        "# Index",
        "",
        "Generated topic digests for downstream human and LLM readers.",
        "",
        "## Topics",
        "",
    ]
    for topic in result.topics:
        file_name = "{slug}.md".format(slug=topic.slug)
        preview_lines = [line.strip() for line in topic.summary.splitlines() if line.strip()]
        preview = " ".join(preview_lines[:2])
        lines.append(
            "- [{title}]({file_name}) — {summary}".format(
                title=topic.title,
                file_name=file_name,
                summary=preview,
            )
        )
    lines.extend(
        [
            "",
            "## Source inputs",
            "",
        ]
    )
    for document in result.documents:
        lines.append("- `{path}`".format(path=document.path_str))
    lines.extend(
        [
            "",
            "## Stop reason",
            "",
            result.stop_reason,
            "",
        ]
    )
    return "\n".join(lines)


class MarkdownArtifactWriter:
    def write(
        self,
        result: DigestResult,
        output_dir: Path,
        progress_reporter: Optional[ProgressReporter] = None,
    ) -> Dict[str, Path]:
        reporter = progress_reporter or NoOpProgressReporter()
        reporter.persist("Writing artifacts to {path}.".format(path=output_dir))
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_paths: Dict[str, Path] = {}
        for topic in result.topics:
            topic_path = output_dir / "{slug}.md".format(slug=topic.slug)
            reporter.update("Writing {name}.".format(name=file_label(topic_path)))
            topic_path.write_text(_render_topic_markdown(topic), encoding="utf-8")
            artifact_paths[topic.slug] = topic_path
            reporter.persist("Generated {path}.".format(path=topic_path))
        index_path = output_dir / "INDEX.md"
        reporter.update("Writing {name}.".format(name=file_label(index_path)))
        index_path.write_text(_render_index_markdown(result), encoding="utf-8")
        artifact_paths["INDEX"] = index_path
        reporter.persist("Generated {path}.".format(path=index_path))
        result.artifact_paths = artifact_paths
        return artifact_paths
