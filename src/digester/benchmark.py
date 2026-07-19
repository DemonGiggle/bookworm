from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .core import DigestConfig
from .core.models import DigestResult, TopicDigest
from .core.presets import resolve_preset
from .interfaces.api import DocumentDigester
from .providers import ProviderSettings, create_provider


CORPUS_DIR = Path(__file__).resolve().parents[2] / "benchmarks" / "corpus"


@dataclass(frozen=True)
class Candidate:
    name: str
    provider: str
    model: str
    preset: str


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def _text(topic: TopicDigest) -> str:
    return "\n".join(
        [topic.slug, topic.title, topic.routing_description, topic.summary]
        + topic.key_points
        + topic.workflow_notes
    ).casefold()


def _ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


def score_result(result: DigestResult, expectations: Dict[str, object]) -> Dict[str, object]:
    topic_texts = [_text(topic) for topic in result.topics]
    all_text = "\n".join(topic_texts)
    expected_topics = expectations.get("topics") or []
    matched_topics = 0
    expected_pairs: Set[Tuple[int, str]] = set()
    predicted_pairs: Set[Tuple[int, str]] = set()
    matched_expected_by_topic: Dict[int, int] = {}
    for expected_index, expected in enumerate(expected_topics):
        if not isinstance(expected, dict):
            continue
        terms = [str(term).casefold() for term in expected.get("match_any") or []]
        matching_indexes = [
            index for index, text in enumerate(topic_texts) if any(term in text for term in terms)
        ]
        if matching_indexes:
            matched_topics += 1
        for index in matching_indexes:
            matched_expected_by_topic.setdefault(index, expected_index)
        expected_pairs.update(
            (expected_index, Path(str(value)).name)
            for value in expected.get("source_paths") or []
        )

    actionable = [str(value).casefold() for value in expectations.get("actionable_details") or []]
    retained_actions = sum(value in all_text for value in actionable)
    for topic_index, topic in enumerate(result.topics):
        expected_index = matched_expected_by_topic.get(topic_index, -1)
        predicted_pairs.update(
            (expected_index, Path(ref.source_path).name) for ref in topic.references
        )
    correct_pairs = predicted_pairs & expected_pairs

    normalized_items = [
        " ".join(item.casefold().split())
        for topic in result.topics
        for item in topic.key_points + topic.workflow_notes
        if item.strip()
    ]
    duplicates = len(normalized_items) - len(set(normalized_items))
    unsupported_terms = [str(value).casefold() for value in expectations.get("unsupported_terms") or []]
    unsupported_hits = sum(term in all_text for term in unsupported_terms)
    words = sum(len(_text(topic).split()) for topic in result.topics)
    return {
        "correctness": {
            "topic_recall": _ratio(matched_topics, len(expected_topics)),
            "actionable_detail_recall": _ratio(retained_actions, len(actionable)),
            "unsupported_claim_hits": unsupported_hits,
        },
        "provenance": {
            "reference_precision": _ratio(len(correct_pairs), len(predicted_pairs)),
            "reference_recall": _ratio(len(correct_pairs), len(expected_pairs)),
        },
        "stability": {
            "duplicate_item_rate": _ratio(duplicates, len(normalized_items)),
        },
        "style": {
            "topic_count": len(result.topics),
            "total_words": words,
            "average_words_per_topic": round(words / len(result.topics), 2) if result.topics else 0.0,
        },
    }


def _run_once(candidate: Candidate, corpus_paths: Sequence[Path], output_dir: Path) -> Tuple[DigestResult, float]:
    preset = resolve_preset(candidate.preset)
    api_key_env = "OPENCODE_API_KEY" if candidate.provider == "opencode-go" else "OPENAI_API_KEY"
    provider = create_provider(
        ProviderSettings(
            provider_kind=candidate.provider,
            model=candidate.model,
            api_key=os.getenv(api_key_env, ""),
            base_url=os.getenv("DIGESTER_BASE_URL") or None,
            organization=os.getenv("OPENAI_ORG_ID") or None,
            ollama_host=os.getenv("OLLAMA_HOST", "127.0.0.1"),
            ollama_port=int(os.getenv("OLLAMA_PORT") or "11434"),
            digest_temperature=preset.digest_temperature,
            finalize_temperature=preset.finalize_temperature,
        )
    )
    provider.validate_configuration()
    started = time.perf_counter()
    result = DocumentDigester(
        provider=provider,
        config=DigestConfig(
            max_chunk_tokens=preset.max_chunk_tokens,
            context_window_tokens=preset.context_window_tokens,
            reserved_context_tokens=preset.reserved_context_tokens,
            batch_size=preset.batch_size,
            max_active_topics=preset.max_active_topics,
            max_active_topic_tokens=preset.max_active_topic_tokens,
        ),
    ).digest_paths(corpus_paths, output_dir)
    return result, time.perf_counter() - started


def run_benchmark(
    candidates: Sequence[Candidate], corpus_dir: Path, output_dir: Path, repetitions: int = 2
) -> Dict[str, object]:
    manifest = json.loads((corpus_dir / "manifest.json").read_text(encoding="utf-8"))
    corpus_paths = [corpus_dir / value for value in manifest["files"]]
    output_dir.mkdir(parents=True, exist_ok=True)
    runs = []
    for candidate in candidates:
        results: List[DigestResult] = []
        elapsed: List[float] = []
        failures: List[str] = []
        for index in range(repetitions):
            try:
                result, duration = _run_once(
                    candidate, corpus_paths, output_dir / candidate.name / "run-{0}".format(index + 1)
                )
                results.append(result)
                elapsed.append(duration)
            except Exception as error:  # benchmark failures belong in the report
                failures.append("{0}: {1}".format(type(error).__name__, error))
        scores = score_result(results[0], manifest["expectations"]) if results else None
        slug_sets = [{topic.slug for topic in result.topics} for result in results]
        if scores is not None:
            union_slugs = set.union(*slug_sets)
            scores["stability"]["slug_stability"] = (
                1.0
                if len(slug_sets) < 2 or not union_slugs
                else round(len(set.intersection(*slug_sets)) / len(union_slugs), 4)
            )
        preset = resolve_preset(candidate.preset)
        runs.append(
            {
                "candidate": asdict(candidate),
                "parameters": preset.metadata(),
                "scores": scores,
                "operations": {
                    "repetitions": repetitions,
                    "successful_runs": len(results),
                    "failure_count": len(failures),
                    "failures": failures,
                    "elapsed_seconds": [round(value, 4) for value in elapsed],
                    "input_tokens": None,
                    "output_tokens": None,
                    "estimated_cost_usd": None,
                    "note": "Token and cost metrics are null when the provider does not expose usage.",
                },
            }
        )
    return {
        "schema_version": 1,
        "code_commit": _git_commit(),
        "corpus": {
            "revision": manifest["revision"],
            "license": manifest["license"],
            "files": manifest["files"],
        },
        "runs": runs,
    }


def _markdown(report: Dict[str, object]) -> str:
    lines = ["# Bookworm benchmark", "", "- Commit: `{0}`".format(report["code_commit"]), "- Corpus: `{0}`".format(report["corpus"]["revision"]), ""]
    for run in report["runs"]:
        candidate = run["candidate"]
        lines.extend(["## {0}".format(candidate["name"]), "", "- Provider/model/preset: `{0}` / `{1}` / `{2}`".format(candidate["provider"], candidate["model"], candidate["preset"]), "- Failures: {0}".format(run["operations"]["failure_count"])])
        if run["scores"]:
            for group in ("correctness", "provenance", "stability", "style"):
                values = ", ".join("{0}={1}".format(key, value) for key, value in sorted(run["scores"][group].items()))
                lines.append("- {0}: {1}".format(group, values))
        lines.append("")
    return "\n".join(lines)


def _candidate(value: str) -> Candidate:
    prefix = value.split(":", 2)
    if len(prefix) != 3 or ":" not in prefix[2]:
        raise argparse.ArgumentTypeError("candidate must be NAME:PROVIDER:MODEL:PRESET")
    model, preset = prefix[2].rsplit(":", 1)
    if not all([prefix[0], prefix[1], model, preset]):
        raise argparse.ArgumentTypeError("candidate must be NAME:PROVIDER:MODEL:PRESET")
    return Candidate(prefix[0], prefix[1], model, preset)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m digester.benchmark")
    parser.add_argument("--candidate", action="append", type=_candidate, dest="candidates")
    parser.add_argument("--corpus-dir", type=Path, default=CORPUS_DIR)
    parser.add_argument("--output-dir", type=Path, default=Path("benchmark-results"))
    parser.add_argument("--repetitions", type=int, default=2)
    args = parser.parse_args(argv)
    candidates = args.candidates or [Candidate("mock-local", "mock-llm", "fixture", "local-26b"), Candidate("mock-frontier", "mock-llm", "fixture", "frontier")]
    report = run_benchmark(candidates, args.corpus_dir, args.output_dir, args.repetitions)
    (args.output_dir / "results.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (args.output_dir / "report.md").write_text(_markdown(report) + "\n", encoding="utf-8")
    print("Wrote {0} and {1}".format(args.output_dir / "results.json", args.output_dir / "report.md"))
    return 0 if all(run["operations"]["failure_count"] == 0 for run in report["runs"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
