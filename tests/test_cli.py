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
    assert "INDEX.md" in captured.out
    assert (output_dir / "summary.md").exists()


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

    capsys.readouterr()
    assert exit_code == 0
    assert seen == {
        "provider_kind": "ollama",
        "ollama_host": "192.168.1.10",
        "ollama_port": 11555,
    }
