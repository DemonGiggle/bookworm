# Bookworm Digester

Bookworm Digester ingests source documents, incrementally digests them through an LLM-guided loop, and writes section-like skill files into agent-native skill directories for downstream Copilot, OpenCode, and Codex workflows as topics evolve and then finalize.

Each output file is meant to behave like a reusable skill file for another agent: focused enough to stand alone, but still traceable back to the source material.

Generated `SKILL.md` files preserve dedicated skill-routing data instead of inferring it from the first summary line. Each skill includes:

- YAML frontmatter with an explicit routing `description`
- `## When To Use` generated from dedicated routing guidance
- `## Purpose` for the durable summary
- `## Core Instructions` and `## Workflow Notes` for action-oriented detail
- source files and source references

Before export, Bookworm validates finalized topics so weak routing text, thin workflow guidance, or missing references fail explicitly instead of quietly producing low-signal skills.

By default, each run writes three directories beneath the chosen output directory:

```text
out/
├── copilot/
│   ├── INSTALL.md
│   └── .github/skills/<skill-name>/SKILL.md
├── opencode/
│   ├── INSTALL.md
│   └── .opencode/skills/<skill-name>/SKILL.md
└── codex/
    ├── INSTALL.md
    └── .agents/skills/<skill-name>/SKILL.md
```

Each agent root also includes a short `INSTALL.md` that lists the documented project and global locations for that agent's skills.

## Supported inputs

- Plain text and markdown
- PDF
- DOCX
- XLSX/XLSM

## Provider model

- `openai`: hosted OpenAI models
- `openai-compatible`: local or self-hosted models that expose an OpenAI-compatible API
- `ollama`: local Ollama server via `http://<host>:<port>/api/chat`
- `mock-llm`: deterministic fake output for fast end-to-end validation without a real LLM call

## CLI example

```bash
export OPENAI_API_KEY=your-api-key

bookworm digest docs/*.txt \
  --output-dir out \
  --provider-kind openai \
  --model gpt-4.1-mini \
  --max-active-topics 16
```

You can also keep the key in a file and point the CLI at it:

```bash
bookworm digest docs/*.txt \
  --output-dir out \
  --provider-kind openai \
  --model gpt-4.1-mini \
  --api-key-file ~/.config/bookworm/openai.key \
  --max-active-topics 16
```

## Ollama example

```bash
bookworm digest docs/*.txt \
  --output-dir out \
  --provider-kind ollama \
  --model llama3.1 \
  --ollama-host 127.0.0.1 \
  --ollama-port 11434 \
  --verbose
```

If `--ollama-port` is omitted, the CLI defaults to port `11434`.
Use `--verbose` or `-v` to print truncated LLM request and response previews, total character counts, and round-trip timing for each model call.
Use `--vv` to log the full escaped request and response bodies without omitting the middle.
Use `--log-location stdio|/path/to/bookworm.log` to keep logs on stdio or write them to a file. The default is `stdio`.
If an Ollama model returns malformed JSON, Bookworm retries once with a stricter JSON-only instruction. If it still fails, reduce `--batch-size`, `--max-chunk-chars`, or `--max-active-topics`, or choose a model with better structured-output reliability.

## MockLLM example

```bash
bookworm digest docs/*.txt \
  --output-dir out \
  --provider-kind mock-llm \
  --model fake-model
```

`mock-llm` does not require an API key and intentionally produces synthetic placeholder topics from source metadata so you can validate ingestion, orchestration, and artifact export flows quickly.

After a successful run, the CLI prints a short status report to stdout with the chunk count, configured and realized batch sizes, total chunk chars, batch count, elapsed digestion time, and generated skill count.

## Loop semantics

The digester always keeps processing remaining chunks unless it hits `--max-batches`. The provider's `should_continue` flag is narrower: it tells the orchestrator whether the **currently visible** section-like topics likely continue into adjacent chunks, not whether the whole corpus is finished. After each batch, Bookworm rewrites the current in-progress skill files so partial progress is preserved on disk. When the provider marks the visible cluster complete, Bookworm finalizes and rewrites those topic files immediately, then continues scanning later chunks for new topics. If finalization fails, Bookworm leaves the latest in-progress files on disk before surfacing the error.
