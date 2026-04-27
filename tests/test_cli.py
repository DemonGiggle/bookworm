from pathlib import Path

from digester.core.models import DigestBatchRequest, DigestDecision, TopicDigest
from digester.interfaces import cli
from digester.providers import ProviderSettings
from digester.providers.base import LLMProvider


class CliFakeProvider(LLMProvider):
    def __init__(self) -> None:
        self.validation_calls = 0

    def validate_configuration(self) -> None:
        self.validation_calls += 1

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
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

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
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Wrote 1 skill(s) for 3 agent target(s)" in captured.out
    assert (output_dir / "copilot" / ".github" / "skills" / "summary" / "SKILL.md").exists()
    assert (output_dir / "opencode" / ".opencode" / "skills" / "summary" / "SKILL.md").exists()
    assert (output_dir / "codex" / ".agents" / "skills" / "summary" / "SKILL.md").exists()
    assert (output_dir / "copilot" / "INSTALL.md").exists()
    assert (output_dir / "opencode" / "INSTALL.md").exists()
    assert (output_dir / "codex" / "INSTALL.md").exists()
    assert "Using provider openai with model fake-model." in captured.err
    assert "Loaded notes.txt with 1 section(s)." in captured.err
    assert "Completed batch 1/1; tracking 1 topic(s)." in captured.err
    assert "Finished digestion with 1 skill file(s)." in captured.err
    assert "Generated" in captured.err


def test_cli_validates_provider_before_digestion(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    provider = CliFakeProvider()
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setattr(cli, "create_provider", lambda settings: provider)

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--model",
            "fake-model",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert provider.validation_calls == 1


def test_cli_reports_validation_errors_without_traceback(monkeypatch, tmp_path: Path, capsys) -> None:
    class FailingProvider(CliFakeProvider):
        def validate_configuration(self) -> None:
            raise ValueError("OpenAI project does not have access to model fake-model.")

    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setattr(cli, "create_provider", lambda settings: FailingProvider())

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--model",
            "fake-model",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "Error: OpenAI project does not have access to model fake-model." in captured.err
    assert "Starting digestion" not in captured.err
    assert captured.out == ""


def test_cli_reads_api_key_from_file(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    api_key_path = tmp_path / "openai.key"
    api_key_path.write_text("file-key\n", encoding="utf-8")
    seen = {}

    def fake_create_provider(settings: ProviderSettings):
        seen["api_key"] = settings.api_key
        return CliFakeProvider()

    monkeypatch.setattr(cli, "create_provider", fake_create_provider)

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--model",
            "fake-model",
            "--api-key-file",
            str(api_key_path),
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert seen["api_key"] == "file-key"


def test_cli_reads_api_key_from_custom_environment_variable(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    seen = {}
    monkeypatch.setenv("BOOKWORM_OPENAI_API_KEY", "custom-key")

    def fake_create_provider(settings: ProviderSettings):
        seen["api_key"] = settings.api_key
        return CliFakeProvider()

    monkeypatch.setattr(cli, "create_provider", fake_create_provider)

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--model",
            "fake-model",
            "--api-key-env",
            "BOOKWORM_OPENAI_API_KEY",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert seen["api_key"] == "custom-key"


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


def test_cli_passes_ollama_timeout_when_specified(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    seen = {}

    def fake_create_provider(settings: ProviderSettings):
        seen["timeout_seconds"] = settings.timeout_seconds
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
            "--timeout-sc",
            "600",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert seen["timeout_seconds"] == 600


def test_cli_ollama_timeout_defaults_to_none(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    seen = {}

    def fake_create_provider(settings: ProviderSettings):
        seen["timeout_seconds"] = settings.timeout_seconds
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
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert seen["timeout_seconds"] is None


def test_cli_mock_llm_runs_without_api_key(tmp_path: Path, monkeypatch, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--provider-kind",
            "mock-llm",
            "--model",
            "fake-model",
            "--batch-size",
            "1",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert (output_dir / "copilot" / ".github" / "skills" / "mock-notes" / "SKILL.md").exists()
    assert (output_dir / "opencode" / ".opencode" / "skills" / "mock-notes" / "SKILL.md").exists()
    assert (output_dir / "codex" / ".agents" / "skills" / "mock-notes" / "SKILL.md").exists()
    assert (output_dir / "copilot" / "INSTALL.md").exists()
    assert (output_dir / "opencode" / "INSTALL.md").exists()
    assert (output_dir / "codex" / "INSTALL.md").exists()
    assert "Using provider mock-llm with model fake-model." in captured.err
    assert "Wrote 1 skill(s) for 3 agent target(s)" in captured.out


def test_cli_mock_llm_writes_distinct_skills_for_duplicate_source_stems(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    first_dir = tmp_path / "first"
    second_dir = tmp_path / "second"
    first_dir.mkdir()
    second_dir.mkdir()
    first_input = first_dir / "notes.txt"
    second_input = second_dir / "notes.txt"
    first_input.write_text("Alpha content.", encoding="utf-8")
    second_input.write_text("Beta content.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    exit_code = cli.main(
        [
            "digest",
            str(first_input),
            str(second_input),
            "--output-dir",
            str(output_dir),
            "--provider-kind",
            "mock-llm",
            "--model",
            "fake-model",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    for slug in ("mock-notes", "mock-notes-2"):
        assert (output_dir / "copilot" / ".github" / "skills" / slug / "SKILL.md").exists()
        assert (output_dir / "opencode" / ".opencode" / "skills" / slug / "SKILL.md").exists()
        assert (output_dir / "codex" / ".agents" / "skills" / slug / "SKILL.md").exists()
    assert "Wrote 2 skill(s) for 3 agent target(s)" in captured.out


def test_cli_max_topics_flag_is_kept_as_compatibility_alias() -> None:
    args = cli.build_parser().parse_args(
        [
            "digest",
            "notes.txt",
            "--output-dir",
            "artifacts",
            "--model",
            "fake-model",
            "--provider-kind",
            "mock-llm",
            "--max-topics",
            "7",
        ]
    )

    assert args.max_active_topics == 7
