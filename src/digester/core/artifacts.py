from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional, Sequence, Set, Tuple

from ..utils.progress import NoOpProgressReporter, ProgressReporter, file_label
from .models import DigestResult, TopicDigest


@dataclass(frozen=True)
class AgentSkillLayout:
    agent_name: str
    skills_path_parts: Tuple[str, ...]
    compatibility: Optional[str] = None
    project_install_path: str = ""
    global_install_path: str = ""


DEFAULT_AGENT_LAYOUTS: Tuple[AgentSkillLayout, ...] = (
    AgentSkillLayout(
        agent_name="copilot",
        skills_path_parts=(".github", "skills"),
        project_install_path=".github/skills/<skill-name>/SKILL.md",
        global_install_path="~/.copilot/skills/<skill-name>/SKILL.md",
    ),
    AgentSkillLayout(
        agent_name="opencode",
        skills_path_parts=(".opencode", "skills"),
        compatibility="opencode",
        project_install_path=".opencode/skills/<skill-name>/SKILL.md",
        global_install_path="~/.config/opencode/skills/<skill-name>/SKILL.md",
    ),
    AgentSkillLayout(
        agent_name="codex",
        skills_path_parts=(".agents", "skills"),
        project_install_path=".agents/skills/<skill-name>/SKILL.md",
        global_install_path="~/.agents/skills/<skill-name>/SKILL.md",
    ),
)


def _unique_source_paths(topic: TopicDigest):
    seen = set()
    ordered = []
    for ref in topic.references:
        if ref.source_path in seen:
            continue
        seen.add(ref.source_path)
        ordered.append(ref.source_path)
    return ordered


def _topic_routing_description(topic: TopicDigest) -> str:
    summary = topic.summary.strip()
    first_line = next((line.strip() for line in summary.splitlines() if line.strip()), topic.title)
    normalized = first_line.rstrip(".")
    return "Use this skill when work requires {summary}.".format(summary=normalized)


def _render_skill_body(topic: TopicDigest) -> str:
    summary = topic.summary.strip()
    lines = [
        "# {title}".format(title=topic.title),
        "",
        "## When To Use",
        "",
        _topic_routing_description(topic),
        "",
        "## Purpose",
        "",
        summary,
        "",
        "## Core Instructions",
        "",
    ]
    lines.extend("- {point}".format(point=point) for point in topic.key_points)
    lines.extend(
        [
            "",
            "## Workflow Notes",
            "",
            "- Load this skill when the task matches the frontmatter description and the guidance below.",
            "- Treat the instructions above as source-backed context, not as a replacement for checking current repository code.",
            "- Use the source references when a decision depends on exact wording, provenance, or missing detail.",
        ]
    )
    source_paths = _unique_source_paths(topic)
    if source_paths:
        lines.extend(["", "## Source files", ""])
        lines.extend("- `{path}`".format(path=path) for path in source_paths)
    lines.extend(["", "## Source references", ""])
    lines.extend("- {ref}".format(ref=ref.render()) for ref in topic.references)
    lines.append("")
    return "\n".join(lines)


def _normalize_skill_dir_name(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized or "skill"


def _render_skill_markdown(
    topic: TopicDigest,
    layout: AgentSkillLayout,
    skill_dir_name: str,
) -> str:
    frontmatter_lines = [
        "---",
        "name: {name}".format(name=skill_dir_name),
        "description: {description}".format(description=json.dumps(_topic_routing_description(topic))),
    ]
    if layout.compatibility:
        frontmatter_lines.append("compatibility: {compatibility}".format(compatibility=layout.compatibility))
    frontmatter_lines.extend(["---", ""])
    return "\n".join(frontmatter_lines) + _render_skill_body(topic)


def _render_install_markdown(layout: AgentSkillLayout) -> str:
    return "\n".join(
        [
            "# Install",
            "",
            "Project: `{path}`".format(path=layout.project_install_path),
            "Global: `{path}`".format(path=layout.global_install_path),
            "",
        ]
    )


class MarkdownArtifactWriter:
    def __init__(self, agent_layouts: Sequence[AgentSkillLayout] = DEFAULT_AGENT_LAYOUTS) -> None:
        self.agent_layouts = tuple(agent_layouts)
        self._skill_dir_names: Dict[str, str] = {}
        self._used_skill_dir_names: Set[str] = set()
        self._install_doc_paths: Dict[str, Path] = {}

    def _write_install_doc(
        self,
        layout: AgentSkillLayout,
        agent_root: Path,
        progress_reporter: ProgressReporter,
    ) -> Path:
        install_doc_path = self._install_doc_paths.get(layout.agent_name)
        if install_doc_path is not None and install_doc_path.exists():
            return install_doc_path
        if install_doc_path is None:
            install_doc_path = agent_root / "INSTALL.md"
            self._install_doc_paths[layout.agent_name] = install_doc_path
        install_doc_path.write_text(_render_install_markdown(layout), encoding="utf-8")
        progress_reporter.persist("Generated {path}.".format(path=install_doc_path))
        return install_doc_path

    def _skill_dir_name_for(self, topic: TopicDigest) -> str:
        existing = self._skill_dir_names.get(topic.slug)
        if existing is not None:
            return existing
        base_name = _normalize_skill_dir_name(topic.slug)
        candidate = base_name
        suffix = 2
        while candidate in self._used_skill_dir_names:
            candidate = "{base}-{suffix}".format(base=base_name, suffix=suffix)
            suffix += 1
        self._used_skill_dir_names.add(candidate)
        self._skill_dir_names[topic.slug] = candidate
        return candidate

    def write_topics(
        self,
        topics: Sequence[TopicDigest],
        output_dir: Path,
        progress_reporter: Optional[ProgressReporter] = None,
    ) -> Dict[str, Path]:
        reporter = progress_reporter or NoOpProgressReporter()
        output_dir.mkdir(parents=True, exist_ok=True)
        artifact_paths: Dict[str, Path] = {}
        for layout in self.agent_layouts:
            agent_root = output_dir / layout.agent_name
            skills_root = agent_root.joinpath(*layout.skills_path_parts)
            skills_root.mkdir(parents=True, exist_ok=True)
            artifact_paths[layout.agent_name] = agent_root
            artifact_paths["{agent}:install".format(agent=layout.agent_name)] = self._write_install_doc(
                layout,
                agent_root,
                reporter,
            )
            for topic in topics:
                skill_dir_name = self._skill_dir_name_for(topic)
                skill_path = skills_root / skill_dir_name / "SKILL.md"
                skill_path.parent.mkdir(parents=True, exist_ok=True)
                reporter.update("Writing {name}.".format(name=file_label(skill_path)))
                skill_path.write_text(
                    _render_skill_markdown(topic, layout, skill_dir_name),
                    encoding="utf-8",
                )
                artifact_paths["{agent}:{slug}".format(agent=layout.agent_name, slug=topic.slug)] = skill_path
                reporter.persist("Generated {path}.".format(path=skill_path))
        return artifact_paths

    def write_index(
        self,
        result: DigestResult,
        output_dir: Path,
        progress_reporter: Optional[ProgressReporter] = None,
    ) -> Path:
        del result
        del progress_reporter
        output_dir.mkdir(parents=True, exist_ok=True)
        return output_dir

    def write(
        self,
        result: DigestResult,
        output_dir: Path,
        progress_reporter: Optional[ProgressReporter] = None,
    ) -> Dict[str, Path]:
        reporter = progress_reporter or NoOpProgressReporter()
        reporter.persist("Writing artifacts to {path}.".format(path=output_dir))
        artifact_paths = self.write_topics(
            result.topics,
            output_dir,
            progress_reporter=reporter,
        )
        result.artifact_paths = artifact_paths
        return artifact_paths
