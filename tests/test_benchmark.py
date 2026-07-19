import json
from pathlib import Path

from digester import benchmark


def test_deterministic_benchmark_writes_comparable_reports(tmp_path: Path) -> None:
    output_dir = tmp_path / "results"
    exit_code = benchmark.main(["--output-dir", str(output_dir), "--repetitions", "2"])

    assert exit_code == 0
    payload = json.loads((output_dir / "results.json").read_text(encoding="utf-8"))
    assert payload["schema_version"] == 1
    assert payload["corpus"]["revision"] == "bookworm-public-v1"
    assert [run["candidate"]["preset"] for run in payload["runs"]] == [
        "local-26b",
        "frontier",
    ]
    assert all(run["operations"]["failure_count"] == 0 for run in payload["runs"])
    assert all(run["scores"]["stability"]["slug_stability"] == 1.0 for run in payload["runs"])
    report = (output_dir / "report.md").read_text(encoding="utf-8")
    assert "correctness:" in report
    assert "provenance:" in report
    assert "style:" in report


def test_candidate_requires_all_four_fields() -> None:
    try:
        benchmark._candidate("local:ollama:model")
    except Exception as error:
        assert "NAME:PROVIDER:MODEL:PRESET" in str(error)
    else:
        raise AssertionError("invalid candidate was accepted")


def test_candidate_preserves_colons_in_model_name() -> None:
    candidate = benchmark._candidate("local:ollama:gemma4:26b:local-26b")
    assert candidate.model == "gemma4:26b"
    assert candidate.preset == "local-26b"
