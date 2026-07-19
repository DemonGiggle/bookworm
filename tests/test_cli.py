from pathlib import Path

import pytest

from digester.core.models import DigestBatchRequest, DigestDecision, TopicDigest
from digester.images import MockImageAnalyzer
from digester.interfaces import cli
from digester.providers import ProviderSettings
from digester.providers.base import LLMProvider
from digester.utils.progress import ConsoleProgressReporter


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
                    routing_description="Use this skill when reviewing the concise document summary.",
                    summary="Captures the essential content and preserves the main points for downstream review.",
                    key_points=[
                        "Produces markdown output",
                        "Preserves source-backed guidance for later review",
                    ],
                    workflow_notes=["Open the generated skill before sharing it with another agent."],
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
    assert "Digest status report:" in captured.out
    assert "- Chunks: 1" in captured.out
    assert "- Configured batch size: 2" in captured.out
    assert "- Batch sizes: 1" in captured.out
    assert "- Total chars: 19" in captured.out
    assert "- Batches: 1" in captured.out
    assert "- Elapsed: " in captured.out
    assert "- Skills generated: 1" in captured.out
    assert (output_dir / "copilot" / ".github" / "skills" / "summary" / "SKILL.md").exists()
    assert (output_dir / "opencode" / ".opencode" / "skills" / "summary" / "SKILL.md").exists()
    assert (output_dir / "codex" / ".agents" / "skills" / "summary" / "SKILL.md").exists()
    assert (output_dir / "copilot" / "INSTALL.md").exists()
    assert (output_dir / "opencode" / "INSTALL.md").exists()
    assert (output_dir / "codex" / "INSTALL.md").exists()
    assert "Using provider openai with model fake-model." in captured.err
    assert 'Resolved model preset: {"batch_size": 2' in captured.err
    assert "Loaded notes.txt with 1 section(s)." in captured.err
    assert "Completed batch 1/1; tracking 1 topic(s)." in captured.err
    assert "Finished digestion with 1 skill file(s)." in captured.err
    assert "Generated" in captured.err


def test_cli_rejects_text_only_image_analyzer(tmp_path: Path) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("Notes.", encoding="utf-8")

    with pytest.raises(SystemExit):
        cli.main(
            [
                "digest",
                str(input_path),
                "--output-dir",
                str(tmp_path / "out"),
                "--model",
                "text-model",
                "--image-analyzer-kind",
                "ollama",
                "--image-capability",
                "text-only",
            ]
        )


def test_cli_digest_command_passes_recursive_directory_flag(monkeypatch, tmp_path: Path, capsys) -> None:
    docs_dir = tmp_path / "docs"
    nested_dir = docs_dir / "guides"
    nested_dir.mkdir(parents=True)
    (docs_dir / "overview.txt").write_text("overview", encoding="utf-8")
    (nested_dir / "setup.py").write_text("print('nested')\n", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")
    monkeypatch.setattr(cli, "create_provider", lambda settings: CliFakeProvider())

    exit_code = cli.main(
        [
            "digest",
            str(docs_dir),
            "--recursive",
            "--output-dir",
            str(output_dir),
            "--model",
            "fake-model",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "Loaded overview.txt with 1 section(s)." in captured.err
    assert "Loaded setup.py with 1 section(s)." in captured.err


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


def test_cli_reads_opencode_go_api_key_from_default_environment(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    seen = {}
    monkeypatch.setenv("OPENCODE_API_KEY", "go-key")

    def fake_create_provider(settings: ProviderSettings):
        seen["provider_kind"] = settings.provider_kind
        seen["api_key"] = settings.api_key
        return CliFakeProvider()

    monkeypatch.setattr(cli, "create_provider", fake_create_provider)

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--provider-kind",
            "opencode-go",
            "--model",
            "opencode-go/kimi-k3",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert seen == {"provider_kind": "opencode-go", "api_key": "go-key"}


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


def test_cli_passes_verbose_reporter_to_provider(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    provider = CliFakeProvider()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "create_provider", lambda settings: provider)

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
            "--verbose",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert isinstance(provider.progress_reporter, ConsoleProgressReporter)
    assert provider.progress_reporter.verbosity() == 1


def test_cli_short_verbose_flag_is_supported() -> None:
    args = cli.build_parser().parse_args(
        [
            "digest",
            "notes.txt",
            "--output-dir",
            "artifacts",
            "--provider-kind",
            "mock-llm",
            "--model",
            "fake-model",
            "-v",
        ]
    )

    assert args.verbose is True
    assert args.vv is False


def test_cli_double_verbose_flag_is_supported() -> None:
    args = cli.build_parser().parse_args(
        [
            "digest",
            "notes.txt",
            "--output-dir",
            "artifacts",
            "--provider-kind",
            "mock-llm",
            "--model",
            "fake-model",
            "--vv",
        ]
    )

    assert args.vv is True
    assert args.verbose is False


def test_cli_passes_double_verbose_reporter_to_provider(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    provider = CliFakeProvider()
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "create_provider", lambda settings: provider)

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
            "--vv",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert isinstance(provider.progress_reporter, ConsoleProgressReporter)
    assert provider.progress_reporter.verbosity() == 2


def test_cli_writes_logs_to_file(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    log_path = tmp_path / "logs" / "bookworm.log"
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
            "--log-location",
            str(log_path),
        ]
    )

    captured = capsys.readouterr()
    log_text = log_path.read_text(encoding="utf-8")
    assert exit_code == 0
    assert "Using provider mock-llm with model fake-model." not in captured.err
    assert "Using provider mock-llm with model fake-model." in log_text
    assert "Finished digestion with 1 skill file(s)." in log_text


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


def test_cli_status_report_lists_multiple_batch_sizes(tmp_path: Path, monkeypatch, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text(
        "One.\n\nTwo.\n\nThree.",
        encoding="utf-8",
    )
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
            "2",
            "--max-chunk-chars",
            "8",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "- Chunks: 3" in captured.out
    assert "- Configured batch size: 2" in captured.out
    assert "- Batch sizes: 2, 1" in captured.out
    assert "- Total chars: 14" in captured.out
    assert "- Batches: 2" in captured.out
    assert "- Skills generated: 1" in captured.out


def test_cli_creates_configured_image_analyzer(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    seen = {}

    def fake_create_image_analyzer(settings):
        seen["analyzer_kind"] = settings.analyzer_kind
        seen["model"] = settings.model
        seen["temperature"] = settings.temperature
        return MockImageAnalyzer(model=settings.model)

    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(cli, "create_provider", lambda settings: CliFakeProvider())
    monkeypatch.setattr(cli, "create_image_analyzer", fake_create_image_analyzer)

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
            "--image-analyzer-kind",
            "mock-image",
            "--image-analyzer-model",
            "fake-vision",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert seen == {
        "analyzer_kind": "mock-image",
        "model": "fake-vision",
        "temperature": 0.0,
    }
    assert "Using image analyzer mock-image with model fake-vision." in captured.err


def test_cli_reads_image_analyzer_api_key_when_provider_does_not_need_one(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    seen = {}
    monkeypatch.setenv("OPENAI_API_KEY", "vision-key")

    def fake_create_image_analyzer(settings):
        seen["analyzer_kind"] = settings.analyzer_kind
        seen["api_key"] = settings.api_key
        seen["model"] = settings.model
        return MockImageAnalyzer(model=settings.model)

    monkeypatch.setattr(cli, "create_provider", lambda settings: CliFakeProvider())
    monkeypatch.setattr(cli, "create_image_analyzer", fake_create_image_analyzer)

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
            "--image-analyzer-kind",
            "openai",
            "--image-analyzer-model",
            "fake-vision",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert seen == {
        "analyzer_kind": "openai",
        "api_key": "vision-key",
        "model": "fake-vision",
    }


def test_cli_resolves_primary_and_image_credentials_by_provider(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    seen = {}
    monkeypatch.setenv("OPENCODE_API_KEY", "go-key")
    monkeypatch.setenv("OPENAI_API_KEY", "vision-key")

    def fake_create_provider(settings: ProviderSettings):
        seen["provider_key"] = settings.api_key
        return CliFakeProvider()

    def fake_create_image_analyzer(settings):
        seen["image_key"] = settings.api_key
        return MockImageAnalyzer(model=settings.model)

    monkeypatch.setattr(cli, "create_provider", fake_create_provider)
    monkeypatch.setattr(cli, "create_image_analyzer", fake_create_image_analyzer)

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--provider-kind",
            "opencode-go",
            "--model",
            "kimi-k3",
            "--image-analyzer-kind",
            "openai",
            "--image-analyzer-model",
            "gpt-4.1-mini",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert seen == {"provider_key": "go-key", "image_key": "vision-key"}


def test_cli_image_specific_key_overrides_shared_primary_key(
    monkeypatch, tmp_path: Path, capsys
) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    primary_key = tmp_path / "primary.key"
    primary_key.write_text("primary-key\n", encoding="utf-8")
    seen = {}
    monkeypatch.setenv("BOOKWORM_IMAGE_KEY", "image-key")

    def fake_create_provider(settings: ProviderSettings):
        seen["provider_key"] = settings.api_key
        return CliFakeProvider()

    def fake_create_image_analyzer(settings):
        seen["image_key"] = settings.api_key
        return MockImageAnalyzer(model=settings.model)

    monkeypatch.setattr(cli, "create_provider", fake_create_provider)
    monkeypatch.setattr(cli, "create_image_analyzer", fake_create_image_analyzer)

    exit_code = cli.main(
        [
            "digest",
            str(input_path),
            "--output-dir",
            str(tmp_path / "artifacts"),
            "--provider-kind",
            "openai",
            "--model",
            "text-model",
            "--api-key-file",
            str(primary_key),
            "--image-analyzer-kind",
            "opencode-go",
            "--image-analyzer-model",
            "kimi-k2.6",
            "--image-api-key-env",
            "BOOKWORM_IMAGE_KEY",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert seen == {"provider_key": "primary-key", "image_key": "image-key"}


def test_cli_configures_ollama_image_analyzer_without_api_key(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    seen = {}
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    def fake_create_image_analyzer(settings):
        seen["analyzer_kind"] = settings.analyzer_kind
        seen["api_key"] = settings.api_key
        seen["model"] = settings.model
        seen["ollama_host"] = settings.ollama_host
        seen["ollama_port"] = settings.ollama_port
        seen["timeout_seconds"] = settings.timeout_seconds
        seen["temperature"] = settings.temperature
        return MockImageAnalyzer(model=settings.model)

    monkeypatch.setattr(cli, "create_provider", lambda settings: CliFakeProvider())
    monkeypatch.setattr(cli, "create_image_analyzer", fake_create_image_analyzer)

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
            "--image-analyzer-kind",
            "ollama",
            "--image-analyzer-model",
            "gemma3:4b",
            "--ollama-host",
            "192.168.1.20",
            "--ollama-port",
            "11435",
            "--timeout-sc",
            "60",
            "--image-temperature",
            "0.2",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert seen == {
        "analyzer_kind": "ollama",
        "api_key": "",
        "model": "gemma3:4b",
        "ollama_host": "192.168.1.20",
        "ollama_port": 11435,
        "timeout_seconds": 60,
        "temperature": 0.2,
    }
    assert "Using image analyzer ollama with model gemma3:4b." in captured.err


def test_cli_passes_stage_specific_provider_temperatures(monkeypatch, tmp_path: Path, capsys) -> None:
    input_path = tmp_path / "notes.txt"
    input_path.write_text("A concise document.", encoding="utf-8")
    output_dir = tmp_path / "artifacts"
    seen = {}
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key")

    def fake_create_provider(settings: ProviderSettings):
        seen["digest_temperature"] = settings.digest_temperature
        seen["finalize_temperature"] = settings.finalize_temperature
        seen["finalize_max_output_tokens"] = settings.finalize_max_output_tokens
        seen["finalize_review_model"] = settings.finalize_review_model
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
            "--digest-temperature",
            "0.6",
            "--finalize-temperature",
            "0.2",
            "--finalize-max-output-tokens",
            "9000",
            "--finalize-review-model",
            "grok-4.5",
        ]
    )

    capsys.readouterr()
    assert exit_code == 0
    assert seen == {
        "digest_temperature": 0.6,
        "finalize_temperature": 0.2,
        "finalize_max_output_tokens": 9000,
        "finalize_review_model": "grok-4.5",
    }
