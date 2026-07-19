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
Models cite evidence with batch-local `chunk_id` values. Bookworm resolves those IDs to canonical source paths and locators in application code, rejects unknown IDs, and never fills missing evidence by assigning every source in a batch.
Finalization runs one topic at a time with only that topic's bounded original evidence snippets. Finalizers must preserve the canonical slug, cannot run without evidence text, and receive a hard output-token limit; successfully finalized topics are persisted before the next topic begins.
The model's `should_continue` value is advisory only. Deterministic source/heading transitions plus enforced active-topic and active-token budgets control cluster flushing, and every flush logs a machine-readable `boundary[...]` reason. Use `--max-active-topic-tokens` to tune the active-state ceiling.

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

- UTF-8 text files, including plain text, markdown, programming source files, configuration files, and extensionless text files
- PDF
- DOCX
- XLSX/XLSM

## External tool requirements

Bookworm's Python package dependencies are installed from `pyproject.toml`. Embedded PDF, DOCX, and spreadsheet image extraction relies on Pillow, which is installed with the package. Some embedded image cases also depend on optional system tools:

- Ollama image analysis requires an Ollama server that supports `/api/chat` image payloads and a vision-capable model.
- DOCX images stored as EMF/WMF previews are converted to PNG before vision analysis. Install Inkscape when you need these legacy/vector previews analyzed.
- Supported Inkscape CLIs:
  - Inkscape 0.92.x style: `inkscape --without-gui input.emf --export-png=output.png`
  - Inkscape 1.x style: `inkscape input.emf --export-type=png --export-filename=output.png`
- ImageMagick is used only as a fallback (`magick` or `convert`). ImageMagick 6/7 must be built with an EMF/WMF-capable delegate for these previews; many Linux builds cannot decode EMF by default.

## Provider model

- `openai`: hosted OpenAI models
- `openai-compatible`: local or self-hosted models that expose an OpenAI-compatible API
- `opencode-go`: OpenCode Go models exposed through its OpenAI-compatible chat-completions API
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

Use `--recursive` when an input path is a directory and you want Bookworm to scan nested folders instead of just the directory's top-level supported files.

```bash
bookworm digest path/to/repo \
  --recursive \
  --output-dir out \
  --provider-kind mock-llm \
  --model fake-model
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

Use `--preset local-26b` for conservative local inference defaults (single-chunk batches, 1,024-token chunks, lower temperatures, and smaller active state), or `--preset frontier` for a larger 128k context profile and an 8,192-token finalization budget suitable for reasoning models. Every run logs the fully resolved preset as sorted JSON, and individual CLI options override preset values. The default `legacy` preset preserves the previous 4,096-token finalization budget. Override either preset with `--finalize-max-output-tokens` when a provider needs a different ceiling.

## OpenCode Go example

Subscribe to OpenCode Go, copy its API key, and set `OPENCODE_API_KEY`. Bookworm selects the official Go endpoint automatically, so `--base-url` is not required. Both the raw API model ID and OpenCode's prefixed form are accepted.

```bash
export OPENCODE_API_KEY=your-go-api-key

bookworm digest docs/*.txt \
  --output-dir out \
  --provider-kind opencode-go \
  --model opencode-go/kimi-k3 \
  --preset frontier
```

This integration currently supports Go models served at the official OpenAI-compatible `/chat/completions` endpoint, including Grok, GLM, Kimi, DeepSeek, and MiMo models. Models currently served only through the Anthropic-style `/messages` endpoint (MiniMax and Qwen) fail early with an actionable error instead of being sent to the wrong protocol. The live model list can change; consult the official OpenCode Go documentation or its `/models` endpoint.

Vision-capable Go models can also analyze embedded images through the same endpoint:

```bash
bookworm digest docs/*.pdf \
  --output-dir out \
  --provider-kind opencode-go \
  --model kimi-k2.6 \
  --image-analyzer-kind opencode-go \
  --image-analyzer-model kimi-k2.6
```

Image support varies by model and gateway version; Bookworm sends the multimodal request but does not assume every Go model can accept it. When text and image providers use different credentials, pass `--image-api-key-file` or `--image-api-key-env`. Without image-specific options, explicit primary key options remain shared for backward compatibility; otherwise each provider uses its default environment variable (`OPENCODE_API_KEY` or `OPENAI_API_KEY`).

Vision capability is tied to explicit image-analyzer configuration, never inferred from a model name. Use `--image-capability text-only` to make an incompatible analyzer selection fail before any request.

If `--ollama-port` is omitted, the CLI defaults to port `11434`.
Use `--verbose` or `-v` to print organized, truncated request and response previews, total character counts, and round-trip timing for each model call, including embedded image analyzer calls.
Use `--vv` to log the full request and response bodies without omitting the middle.
Use `--log-location stdio|/path/to/bookworm.log` to keep logs on stdio or write them to a file. The default is `stdio`.
Use `--max-chunk-tokens` to enforce a conservative token-aware hard limit. Optionally set `--context-window-tokens` and `--reserved-context-tokens`; Bookworm reserves prompt/output space and divides the remaining content budget across the batch. `--max-chunk-chars` remains a compatibility ceiling and oversized paragraphs, code, tables, OCR, and unbroken text are now hard-split.
Bookworm supplies explicit JSON Schemas to OpenAI and Ollama and validates every digest and finalize response locally. OpenAI-compatible endpoints retain JSON-object mode because schema support varies, but their responses receive the same local validation. Missing fields, extra fields, and wrong types (including string values such as `"false"` for `should_continue`) trigger one constrained retry; an invalid retry fails explicitly. If a model still fails, reduce `--batch-size`, `--max-chunk-chars`, or `--max-active-topics`, or choose a model with better structured-output reliability.

## MockLLM example

```bash
bookworm digest docs/*.txt \
  --output-dir out \
  --provider-kind mock-llm \
  --model fake-model
```

`mock-llm` does not require an API key and intentionally produces synthetic placeholder topics from source metadata so you can validate ingestion, orchestration, and artifact export flows quickly.

## Embedded image analysis

Bookworm can optionally analyze embedded images from supported PDF, DOCX, XLSX, and XLSM sources and feed the resulting evidence back into the normal topic discovery flow as source-backed chunks.

```bash
bookworm digest docs/*.{pdf,docx,xlsx,xlsm} \
  --output-dir out \
  --provider-kind openai \
  --model gpt-4.1-mini \
  --image-analyzer-kind openai \
  --image-analyzer-model gpt-4.1-mini
```

Use `--image-analyzer-kind ollama` with a local vision-capable Ollama model such as `gemma3:4b`, `gemma3:12b`, `gemma3:27b`, or `qwen3-vl:8b`.

```bash
bookworm digest docs/*.docx \
  --output-dir out \
  --provider-kind ollama \
  --model llama3.1 \
  --image-analyzer-kind ollama \
  --image-analyzer-model gemma3:4b
```

Use `--image-analyzer-kind openai-compatible` to point image analysis at an OpenAI-compatible vision endpoint, or `--image-analyzer-kind mock-image` for deterministic test fixtures without a live model. If no image analyzer is configured, Bookworm keeps the existing text-only path and logs when supported inputs contain embedded images that were skipped.

If a DOCX contains only an embedded EMF/WMF preview, install Inkscape so Bookworm can convert the preview to PNG before sending it to the vision model. Without a working converter, the image is skipped with a warning because most vision APIs reject EMF/WMF bytes directly.

Spreadsheet image extraction requires loading XLSX/XLSM workbooks in normal mode rather than `read_only=True`, so very large spreadsheets with embedded images can use more memory than text-only ingestion.

After a successful run, the CLI prints a short status report to stdout with the chunk count, configured and realized batch sizes, total chunk chars, batch count, elapsed digestion time, and generated skill count.

## Reproducible benchmark

Run `python -m digester.benchmark --output-dir benchmark-results` for the deterministic local-26B versus frontier-preset smoke benchmark. See `benchmarks/README.md` for real-provider candidates, corpus provenance, metrics, and result-comparison rules.

## Loop semantics

The digester always keeps processing remaining chunks unless it hits `--max-batches`. The provider's `should_continue` flag is narrower: it tells the orchestrator whether the **currently visible** section-like topics likely continue into adjacent chunks, not whether the whole corpus is finished. After each batch, Bookworm rewrites the current in-progress skill files so partial progress is preserved on disk. When the provider marks the visible cluster complete, Bookworm finalizes and rewrites those topic files immediately, then continues scanning later chunks for new topics. If finalization fails, Bookworm leaves the latest in-progress files on disk before surfacing the error.
