from __future__ import annotations

from pathlib import Path
from typing import Dict

from .models import DigestResult, TopicDigest


def _render_topic_markdown(topic: TopicDigest) -> str:
    lines = [
        "# {title}".format(title=topic.title),
        "",
        topic.summary.strip(),
        "",
        "## Key points",
        "",
    ]
    lines.extend("- {point}".format(point=point) for point in topic.key_points)
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
        lines.append(
            "- [{title}]({file_name}) — {summary}".format(
                title=topic.title,
                file_name=file_name,
                summary=topic.summary.splitlines()[0] if topic.summary else "",
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
    def write(self, result: DigestResult, output_dir: Path) -> Dict[str, Path]:
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_paths: Dict[str, Path] = {}
        for topic in result.topics:
            topic_path = output_dir / "{slug}.md".format(slug=topic.slug)
            topic_path.write_text(_render_topic_markdown(topic), encoding="utf-8")
            artifact_paths[topic.slug] = topic_path
        index_path = output_dir / "INDEX.md"
        index_path.write_text(_render_index_markdown(result), encoding="utf-8")
        artifact_paths["INDEX"] = index_path
        result.artifact_paths = artifact_paths
        return artifact_paths
