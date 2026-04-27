from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Optional, Sequence

from ..core import DigestConfig
from ..providers import ProviderSettings, create_provider
from ..utils.progress import ConsoleProgressReporter
from .api import DocumentDigester


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="bookworm")
    subparsers = parser.add_subparsers(dest="command", required=True)

    digest_parser = subparsers.add_parser("digest", help="Digest source files into markdown artifacts.")
    digest_parser.add_argument("inputs", nargs="+", help="Input files or directories to digest.")
    digest_parser.add_argument("--output-dir", required=True, help="Directory for markdown outputs.")
    digest_parser.add_argument(
        "--provider-kind",
        default="openai",
        choices=["openai", "openai-compatible", "ollama", "mock-llm"],
        help="LLM provider kind.",
    )
    digest_parser.add_argument("--model", required=True, help="Model name to invoke.")
    credential_parser = digest_parser.add_mutually_exclusive_group()
    credential_parser.add_argument(
        "--api-key-file",
        help="Path to a file that contains only the provider API key.",
    )
    credential_parser.add_argument(
        "--api-key-env",
        help="Environment variable to read the provider API key from. Defaults to OPENAI_API_KEY.",
    )
    digest_parser.add_argument(
        "--base-url",
        default=os.getenv("DIGESTER_BASE_URL", ""),
        help="Base URL for openai-compatible providers.",
    )
    digest_parser.add_argument(
        "--organization",
        default=os.getenv("OPENAI_ORG_ID", ""),
        help="OpenAI organization ID.",
    )
    digest_parser.add_argument(
        "--ollama-host",
        default=os.getenv("OLLAMA_HOST", "127.0.0.1"),
        help="Host or IP for the local Ollama server.",
    )
    digest_parser.add_argument(
        "--ollama-port",
        type=int,
        default=int(os.getenv("OLLAMA_PORT", "11434")),
        help="Port for the local Ollama server.",
    )
    digest_parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print verbose LLM request and response diagnostics.",
    )
    digest_parser.add_argument(
        "--timeout-sc",
        type=int,
        default=None,
        help="Optional request timeout in seconds for Ollama requests. Defaults to no timeout.",
    )
    digest_parser.add_argument("--max-chunk-chars", type=int, default=1800)
    digest_parser.add_argument("--batch-size", type=int, default=2)
    digest_parser.add_argument("--minimum-batches-before-stop", type=int, default=2)
    digest_parser.add_argument("--max-batches", type=int, default=50)
    digest_parser.add_argument(
        "--max-active-topics",
        "--max-topics",
        dest="max_active_topics",
        type=int,
        default=12,
        help="Maximum number of recent section-like topics to include in each provider prompt.",
    )
    return parser


def _provider_message(args: argparse.Namespace) -> str:
    if args.provider_kind == "ollama":
        return "Using provider ollama ({host}:{port}) with model {model}.".format(
            host=args.ollama_host,
            port=args.ollama_port,
            model=args.model,
        )
    return "Using provider {kind} with model {model}.".format(
        kind=args.provider_kind,
        model=args.model,
    )


def _read_api_key_file(path_value: str) -> str:
    api_key = Path(path_value).read_text(encoding="utf-8").strip()
    if not api_key:
        raise ValueError("API key file is empty.")
    if "\n" in api_key or "\r" in api_key:
        raise ValueError("API key file must contain only the API key.")
    return api_key


def _resolve_api_key(args: argparse.Namespace) -> str:
    if args.provider_kind in {"ollama", "mock-llm"}:
        return ""
    if args.api_key_file:
        return _read_api_key_file(args.api_key_file)
    env_var_name = args.api_key_env or "OPENAI_API_KEY"
    api_key = os.getenv(env_var_name, "").strip()
    if not api_key:
        raise ValueError(
            "An API key is required. Set {env_var} or pass --api-key-file.".format(
                env_var=env_var_name
            )
        )
    return api_key


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "digest":
        parser.error("Unknown command.")

    reporter = ConsoleProgressReporter(verbose=args.verbose)
    try:
        reporter.persist(_provider_message(args))
        provider = create_provider(
            ProviderSettings(
                provider_kind=args.provider_kind,
                model=args.model,
                api_key=_resolve_api_key(args),
                base_url=args.base_url or None,
                organization=args.organization or None,
                ollama_host=args.ollama_host,
                ollama_port=args.ollama_port,
                timeout_seconds=args.timeout_sc,
            )
        )
        provider.set_progress_reporter(reporter)
        provider.validate_configuration()
        digester = DocumentDigester(
            provider=provider,
            config=DigestConfig(
                max_chunk_chars=args.max_chunk_chars,
                batch_size=args.batch_size,
                minimum_batches_before_stop=args.minimum_batches_before_stop,
                max_batches=args.max_batches,
                max_active_topics=args.max_active_topics,
            ),
            progress_reporter=reporter,
        )
        result = digester.digest_paths(args.inputs, args.output_dir)
        agent_targets = len([key for key in result.artifact_paths if ":" not in key])
        print(
            "Wrote {count} skill(s) for {agents} agent target(s) to {output_dir}".format(
                count=len(result.topics),
                agents=agent_targets,
                output_dir=args.output_dir,
            )
        )
        return 0
    except ValueError as error:
        reporter.clear()
        reporter.persist("Error: {message}".format(message=error))
        return 1
