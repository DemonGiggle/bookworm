from __future__ import annotations

import argparse
import os
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
        choices=["openai", "openai-compatible", "ollama"],
        help="LLM provider kind.",
    )
    digest_parser.add_argument("--model", required=True, help="Model name to invoke.")
    digest_parser.add_argument("--api-key", default=os.getenv("OPENAI_API_KEY", ""), help="Provider API key.")
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "digest":
        parser.error("Unknown command.")

    reporter = ConsoleProgressReporter()
    reporter.persist(_provider_message(args))
    provider = create_provider(
        ProviderSettings(
            provider_kind=args.provider_kind,
            model=args.model,
            api_key=args.api_key,
            base_url=args.base_url or None,
            organization=args.organization or None,
            ollama_host=args.ollama_host,
            ollama_port=args.ollama_port,
        )
    )
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
    print(
        "Wrote {count} skill/topic files plus INDEX.md to {output_dir}".format(
            count=len(result.topics),
            output_dir=args.output_dir,
        )
    )
    return 0
