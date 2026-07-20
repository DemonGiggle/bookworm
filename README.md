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

## Configuration file

Bookworm reads optional defaults from `~/.local/bookworm/config.toml`. Create the directory and file first:

```bash
mkdir -p ~/.local/bookworm
${EDITOR:-vi} ~/.local/bookworm/config.toml
```

Put CLI option names under the `[digest]` table using snake_case. The following is a complete example for OpenCode Go text and embedded-image digestion. It is valid as written; remove settings you do not need and adjust model, path, and limit values for your workload. See the [configuration reference](docs/configuration.md) for every setting, default, provider-specific behavior, and preset value.

```toml
[digest]
# General input and output behavior. Input paths remain CLI arguments.
output_dir = "./out"
recursive = true

# Named defaults for context, chunking, temperatures, and finalization limits.
preset = "frontier"

# Primary text provider.
provider_kind = "opencode-go"
model = "kimi-k2.6"
finalize_review_model = "grok-4.5"

# Primary credential source. Use api_key_file instead, not in addition, when
# credentials are stored in a file.
api_key_env = "OPENCODE_API_KEY"
# api_key_file = "/home/you/.local/bookworm/opencode.key"

# Used by openai-compatible providers. OpenCode Go selects its URL itself.
base_url = ""
organization = ""

# Ollama connection defaults, used when a provider or image analyzer is Ollama.
ollama_host = "127.0.0.1"
ollama_port = 11434
timeout_sc = 120

# Embedded-image analysis. The analyzer can use openai, openai-compatible,
# opencode-go, ollama, or mock-image.
image_analyzer_kind = "opencode-go"
image_analyzer_model = "kimi-k2.6"
image_capability = "vision"
image_temperature = 0.0

# Optional image-specific credentials. These are useful when the image analyzer
# differs from the primary provider. Omit both to reuse the applicable default.
image_api_key_env = "OPENCODE_API_KEY"
# image_api_key_file = "/home/you/.local/bookworm/image-provider.key"

# Stage-specific generation settings. These override the selected preset.
digest_temperature = 0.1
finalize_temperature = 0.1
finalize_max_output_tokens = 8192

# Chunking and context limits. Integer values are TOML numbers, not strings.
max_chunk_chars = 1800
max_chunk_tokens = 1024
context_window_tokens = 131072
reserved_context_tokens = 16384
batch_size = 2
minimum_batches_before_stop = 2
max_batches = 50
max_active_topics = 8
max_active_topic_tokens = 32768

# Logging. verbose and vv are mutually exclusive when either is true.
verbose = false
vv = false
log_location = "stdio"
```

Positional input paths are deliberately not stored in the file. With this configuration, a run can be shortened to:

```bash
bookworm digest docs/
```

Flags override individual settings for one run:

```bash
bookworm digest docs/ --model kimi-k3 --output-dir alternate-out
```

Unknown sections, unknown setting names, invalid value types, and mutually exclusive settings fail with a configuration error. `api_key_env`/`api_key_file`, `image_api_key_env`/`image_api_key_file`, and `verbose`/`vv` are mutually exclusive pairs. Store credential environment-variable names or key-file paths in the file rather than raw API keys.

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

This integration currently supports Go models served at the official OpenAI-compatible `/chat/completions` endpoint, including Grok, GLM, Kimi, DeepSeek, and MiMo models. Bookworm uses the Go gateway's native strict JSON Schema response mode for digest and finalization reliability. Models currently served only through the Anthropic-style `/messages` endpoint (MiniMax and Qwen) fail early with an actionable error instead of being sent to the wrong protocol. The live model list can change; consult the official OpenCode Go documentation or its `/models` endpoint.

OpenCode Go performs a final evidence-grounding review after topic finalization. By default the same model reviews its own output. For high-stakes documents, `--finalize-review-model grok-4.5` (or another supported Go chat-completions model) assigns that audit to a different model while reusing the same Go credential.

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
