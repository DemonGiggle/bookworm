from pathlib import Path

from digester.core.models import DigestBatchRequest, DigestDecision, TopicDigest
from digester.interfaces import cli
from digester.providers import ProviderSettings
from digester.providers.base import LLMProvider


class CliFakeProvider(LLMProvider):
    def digest_batch(self, request: DigestBatchRequest) -> DigestDecision:
        return DigestDecision(
            topic_updates=[
                TopicDigest(
                    slug="summary",
                    title="Summary",
                    summary="Captures the essential content.",
                    key_points=["Produces markdown output"],
                    references=[chunk.source_ref for chunk in request.chunk_batch],
                )
            ],
            should_continue=False,
            rationale="Enough context collected.",
        )


def test_cli_digest_command(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"

    monkeypatch.setattr(
        cli,
        "create_provider",
        lambda settings: CliFakeProvider(),
    )

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--model",
            "fake-model",
            "--api-key",
            "fake-key",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Wrote 1 skill/topic files plus INDEX.md" in captured.out
    assert (output_dir / "summary.md").exists()
    assert "Using provider openai with model fake-model." in captured.err
    assert "Loaded notes.txt with 1 section(s)." in captured.err
    assert "Completed batch 1/1; tracking 1 topic(s)." in captured.err
    assert "Finished digestion with 1 skill/topic file(s)." in captured.err
    assert "Generated" in captured.err


def test_cli_passes_ollama_host_and_port(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    seen = {}

    def fake_create_provider(settings: ProviderSettings):
        seen["provider_kind"] = settings.provider_kind
        seen["ollama_host"] = settings.ollama_host
        seen["ollama_port"] = settings.ollama_port
        return CliFakeProvider()

    monkeypatch.setattr(cli, "create_provider", fake_create_provider)

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--provider-kind",
            "ollama",
            "--model",
            "llama3.1",
            "--ollama-host",
            "192.168.1.10",
            "--ollama-port",
            "11555",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert seen == {
        "provider_kind": "ollama",
        "ollama_host": "192.168.1.10",
        "ollama_port": 11555,
    }
    assert "Using provider ollama (192.168.1.10:11555) with model llama3.1." in captured.err


def test_cli_max_topics_flag_is_kept_as_compatibility_alias() -> None:
    args = cli.build_parser().parse_args(
        [
            "digest",
            "notes.txt",
            "--output-dir",
            "artifacts",
            "--model",
            "fake-model",
            "--max-topics",
            "7",
        ]
    )

    assert args.max_active_topics == 7
