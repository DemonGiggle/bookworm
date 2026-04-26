# Technical Design

## 1. Overview

Bookworm Digester is a Python package that converts heterogeneous document sources into a compact set of markdown artifacts optimized for downstream LLM and human readers. The current implementation is intentionally modular:

1. **Source adapters** extract raw content from each supported file type.
2. **Canonical models** normalize extracted content into a shared structure.
3. **Chunking** converts document sections into bounded units for incremental LLM digestion.
4. **Digest orchestration** loops through chunk batches, updating a topic map and asking the provider whether the currently visible topics likely continue into adjacent chunks.
5. **Provider abstraction** isolates prompt construction from LLM transport details.
6. **Artifact generation** writes agent-native `SKILL.md` exports for the supported Copilot, OpenCode, and Codex directory layouts.

This design keeps the core workflow stable while allowing new source types and new LLM backends to be added without rewriting the pipeline.

## 2. Repository Layout

```text
bookworm/
├── docs/
│   ├── spec.md
│   └── technical.md
├── src/
│   └── digester/
│       ├── core/
│       │   ├── artifacts.py
│       │   ├── chunking.py
│       │   ├── models.py
│       │   ├── orchestrator.py
│       │   └── prompts.py
│       ├── interfaces/
│       │   ├── api.py
│       │   └── cli.py
│       ├── providers/
│       │   ├── base.py
│       │   ├── factory.py
│       │   ├── openai_compatible.py
│       │   └── openai_provider.py
│       └── sources/
│           ├── base.py
│           ├── docx.py
│           ├── pdf.py
│           ├── registry.py
│           ├── spreadsheet.py
│           └── text.py
├── tests/
└── pyproject.toml
```

## 3. Package-Level Responsibilities

| Package | Responsibility |
| --- | --- |
| `digester.core` | Canonical data model, chunking rules, prompt construction, orchestration, markdown writing |
| `digester.sources` | File-type-specific extraction and normalization into `SourceDocument` |
| `digester.providers` | Provider abstraction and concrete OpenAI, OpenAI-compatible, and Ollama LLM transports |
| `digester.interfaces` | Public library API and CLI |
| `tests` | Behavioral coverage for adapters, chunking, pipeline, and CLI |

## 4. Canonical Data Model

The core model lives in `src/digester/core/models.py`.

### 4.1 SourceRef

`SourceRef` is the provenance unit used throughout the pipeline. It contains:

- `source_id`: normalized logical identifier for the source document
- `source_path`: original file path
- `locator`: source-local anchor such as `page 3`, `sheet Summary`, or `document-body`

This model is intentionally small because it is serialized into prompt payloads and markdown outputs.

### 4.2 DocumentSection

`DocumentSection` is the canonical extracted section:

- `heading`
- `content`
- `source_ref`

Adapters convert their native structures into a list of sections. This keeps the chunker ignorant of original file formats.

### 4.3 SourceDocument

`SourceDocument` contains:

- `source_id`
- `path`
- `media_type`
- `title`
- `sections`
- `extraction_warnings`

`extraction_warnings` is important for PDF and other lossy sources because it preserves partial extraction quality issues without stopping the pipeline.

### 4.4 ContentChunk

`ContentChunk` is the input unit for the digest loop:

- `chunk_id`
- `source_id`
- `source_path`
- `section_heading`
- `text`
- `source_ref`

Chunks are designed to be provider-facing payloads that remain small enough for repeatable LLM iteration.

### 4.5 TopicDigest

`TopicDigest` is the accumulated section-like skill-file output:

- `slug`
- `title`
- `summary`
- `key_points`
- `references`

The `merge()` method merges topic updates from successive LLM iterations by:

1. Appending additional summary material
2. Deduplicating key points
3. Deduplicating references while preserving order

### 4.6 DigestConfig

`DigestConfig` controls throughput and coverage:

- `max_chunk_chars`
- `batch_size`
- `minimum_batches_before_stop`
- `max_batches`
- `max_active_topics`
- `max_topics` (compatibility alias for `max_active_topics`)

This is the primary place to tune cost, latency, and recall.

## 5. Source Ingestion Pipeline

### 5.1 Registry Dispatch

`SourceRegistry` owns adapter resolution. Its default adapter list is:

1. `PlainTextAdapter`
2. `PdfAdapter`
3. `DocxAdapter`
4. `SpreadsheetAdapter`

It can load both explicit file paths and directories. Directory handling is recursive by one file-system walk level at a time via repeated `load_paths()` calls.

### 5.2 PlainTextAdapter

Supported suffixes:

- `.txt`
- `.md`
- `.rst`

Behavior:

- Reads the file as UTF-8 text
- Wraps the entire file as one `DocumentSection`
- Uses `full-document` as the locator

This adapter is intentionally simple and acts as the baseline ingestion path for notes, exports, and already-clean markdown sources.

### 5.3 PdfAdapter

Supported suffixes:

- `.pdf`

Behavior:

- Uses `pypdf.PdfReader`
- Extracts text page by page
- Emits one section per extractable page
- Records warnings for pages that do not yield text

Current limitation:

- No OCR support exists in v1. Image-only or scanned PDFs will often produce empty pages and warnings rather than usable text.

### 5.4 DocxAdapter

Supported suffixes:

- `.docx`

Behavior:

- Uses `python-docx`
- Reads non-empty paragraphs
- Joins paragraphs with blank lines
- Emits one canonical section for the document body

Current limitation:

- Legacy `.doc` binary files are not yet supported.

### 5.5 SpreadsheetAdapter

Supported suffixes:

- `.xlsx`
- `.xlsm`

Behavior:

- Uses `openpyxl` in read-only, data-only mode
- Iterates each worksheet
- Converts each row into a pipe-delimited textual representation
- Emits one section per worksheet

This makes spreadsheet data digestible by the same text-oriented LLM loop without introducing a second downstream processing path.

## 6. Chunking Strategy

Chunking is implemented in `src/digester/core/chunking.py`.

### 6.1 Algorithm

For each section:

1. Split content on blank lines into paragraph-like units
2. Accumulate paragraphs until `max_chunk_chars` would be exceeded
3. Flush the current chunk
4. Continue until the section is exhausted

### 6.2 Properties

- Keeps semantic paragraphs together when possible
- Preserves a stable source reference at the chunk level
- Produces predictable chunk identifiers such as `source-id-chunk-3`

### 6.3 Current Tradeoffs

- Character count is used instead of tokenizer-aware token count
- Tables represented as line-oriented text may not preserve all spreadsheet semantics
- Cross-section balancing is not attempted

These are acceptable v1 tradeoffs because the architecture keeps chunking isolated and easy to replace.

## 7. Digest Orchestration Loop

The orchestrator lives in `src/digester/core/orchestrator.py`.

### 7.1 Processing Flow

1. Convert normalized documents into chunks
2. Build batch windows using `batch_size`
3. For each batch:
   - pass the currently active topics and new chunks to the provider
   - merge returned topic updates into the in-memory topic map
   - treat `should_continue` as guidance about whether the visible topics likely continue into nearby chunks
4. When the provider marks the visible topic cluster complete, finalize that cluster for export and clear it from the active in-memory map
5. Write completed topic files incrementally
6. Finalize any remaining active topics after the last batch
7. Return a `DigestResult`

### 7.2 Stop Conditions

The loop ends when any of the following happens:

- all computed batches are processed
- `max_batches` is reached

Provider completion does not stop corpus traversal on its own. It only marks the current topic cluster as sufficiently covered.

### 7.3 Why the Loop Is "Adaptive"

The system does not simply summarize the entire corpus in one call. Instead, it exposes incremental state to the provider:

- current topic map
- batch number
- total batches
- new chunk payloads

This allows the provider to accumulate understanding and decide whether visible topics likely need more nearby evidence, while the orchestrator still walks all remaining chunks unless `max_batches` interrupts it.

### 7.4 Merging Behavior

Topic updates from the provider are merged by `slug`. This makes provider output idempotent enough to support iterative digestion:

- the same logical topic can be enriched across batches
- duplicate bullets and references are removed
- summaries are collapsed to reduce line-level repetition

## 8. Prompting Contract

Prompt helpers live in `src/digester/core/prompts.py`.

### 8.1 Digest Prompt

The digest system prompt asks the model to:

- behave as a document digestion engine
- keep output concise and durable
- return strict JSON
- decide whether the visible topics likely need more adjacent chunks

The user prompt includes:

- the current topic map
- the current chunk batch
- hard constraints such as max active topics and anti-duplication guidance

### 8.2 Finalization Prompt

The finalization step asks the model to:

- refine and compress existing topic digests
- preserve factual key points
- return a JSON object with a `topics` list suitable for reusable skill files

### 8.3 Output Schema Expectations

Digest response shape:

```json
{
  "topic_updates": [
    {
      "slug": "architecture",
      "title": "Architecture",
      "summary": "Short summary",
      "key_points": ["Fact 1", "Fact 2"],
      "references": [
        {
          "source_id": "source",
          "source_path": "/tmp/source.txt",
          "locator": "page 1"
        }
      ]
    }
  ],
  "should_continue": true,
  "rationale": "Need more context from adjacent sections for the current visible topic."
}
```

Finalize response shape:

```json
{
  "topics": [
    {
      "slug": "architecture",
      "title": "Architecture",
      "summary": "Final concise summary",
      "key_points": ["Fact 1", "Fact 2"],
      "references": [
        {
          "source_id": "source",
          "source_path": "/tmp/source.txt",
          "locator": "page 1"
        }
      ]
    }
  ]
}
```

## 9. Provider Abstraction

### 9.1 Base Interface

`LLMProvider` defines two operations:

- `digest_batch(request) -> DigestDecision`
- `finalize_topics(topics) -> List[TopicDigest]`

This keeps the orchestration layer independent of vendor SDKs.

### 9.2 OpenAIProvider

`OpenAIProvider`:

- lazily constructs an `OpenAI` client
- sends chat-completion requests with `response_format={"type": "json_object"}`
- parses returned JSON into internal models

### 9.3 OpenAICompatibleProvider

`OpenAICompatibleProvider` subclasses `OpenAIProvider` and requires:

- `model`
- `api_key`
- `base_url`

This is the current extension point for local or self-hosted model servers that expose OpenAI-compatible APIs.

### 9.4 OllamaProvider

`OllamaProvider` integrates with Ollama's native `/api/chat` endpoint and keeps the rest of the pipeline on the same provider contract.

Behavior:

- defaults to `http://127.0.0.1:11434`
- accepts an explicit host/IP and port
- sends `stream: false` and `format: "json"` so the response is a single JSON object
- reuses the same prompt schema and topic parsing behavior as the OpenAI-backed providers

This makes local-model development straightforward without forcing users through an OpenAI-compatible shim.

### 9.5 Provider Factory

`ProviderSettings` and `create_provider()` isolate provider selection from CLI parsing and library orchestration. Current kinds:

- `openai`
- `openai-compatible`
- `ollama`

## 10. Artifact Generation

Markdown writing lives in `src/digester/core/artifacts.py`.

### 10.1 Agent Skill Files

Each generated `SKILL.md` contains:

1. YAML frontmatter with `name` and `description`
2. H1 title
3. `## When To Use`
4. `## Purpose`
5. `## Core Instructions`
6. `## Workflow Notes`
7. `## Source files`
8. `## Source references`

Directory conventions:

- `copilot/.github/skills/{slug}/SKILL.md`
- `opencode/.opencode/skills/{slug}/SKILL.md`
- `codex/.agents/skills/{slug}/SKILL.md`

The description/frontmatter acts as the routing layer for downstream agents, so the runtime no longer emits a separate top-level `INDEX.md`.

## 11. Public Interfaces

### 11.1 Library API

`DocumentDigester` in `src/digester/interfaces/api.py` is the primary library entrypoint.

Typical usage:

```python
from digester.interfaces.api import DocumentDigester
from digester.providers import ProviderSettings, create_provider

provider = create_provider(
    ProviderSettings(
        provider_kind="openai",
        model="gpt-4.1-mini",
        api_key="...",
    )
)

digester = DocumentDigester(provider=provider)
result = digester.digest_paths(["./docs/report.pdf"], "./out")
```

`result.artifact_paths` contains the generated agent root directories (`copilot`, `opencode`, `codex`) plus per-skill `SKILL.md` paths keyed as `<agent>:<topic-slug>`.

### 11.2 CLI

The CLI is defined in `src/digester/interfaces/cli.py`.

Supported command:

```bash
bookworm digest INPUT [INPUT ...] \
  --output-dir OUT \
  --provider-kind openai \
  --model gpt-4.1-mini
```

For hosted providers, the CLI reads credentials from `OPENAI_API_KEY` by default. It also supports:

- `--api-key-env` to select a different environment variable
- `--api-key-file` to read the API key from a file that contains only the key

Tunable runtime parameters:

- `--max-chunk-chars`
- `--batch-size`
- `--minimum-batches-before-stop`
- `--max-batches`
- `--max-topics`

Provider-specific parameters:

- `--provider-kind`
- `--model`
- `--api-key-env`
- `--api-key-file`
- `--base-url`
- `--organization`
- `--ollama-host`
- `--ollama-port`

## 12. Error Handling

Current error behavior is intentionally explicit:

- unsupported source types raise `ValueError`
- empty extractable content raises `ValueError`
- empty model response raises `ValueError`
- missing provider credentials raise `ValueError`

This keeps failures visible instead of silently generating misleading output.

## 13. Testing Strategy

The current test suite covers:

- chunk splitting behavior
- plain text ingestion
- DOCX ingestion
- spreadsheet ingestion
- end-to-end artifact creation using a fake provider
- CLI wiring with a monkeypatched provider factory

The tests intentionally use fake providers for determinism and speed while preserving the orchestration contract.

## 14. Known Limitations

1. No OCR support for scanned PDFs or image-heavy inputs
2. No legacy `.doc` parser
3. No tokenizer-aware chunk budgeting
4. No retry/backoff or rate-limit handling in provider calls
5. No persisted run metadata beyond generated markdown files
6. No streaming or parallel digestion
7. No confidence scoring or coverage reporting per topic

## 15. Extension Roadmap

The current architecture is designed so the following additions are low-friction:

- add OCR-capable adapters or preprocessing
- add tokenizer-aware chunk sizing
- support additional providers such as Anthropic or Gemini
- add a richer citation format in markdown
- add a structured run manifest or JSON export
- expose an HTTP service without changing the core engine
- support retrieval-guided chunk selection instead of strictly sequential batching

## 16. Design Summary

The implementation favors a small, explicit core:

- source-specific parsing is isolated
- the digest loop is stateful but simple
- LLM coupling is constrained to a provider interface
- markdown output is concise and traceable

That gives Bookworm Digester a stable v1 foundation while keeping the architecture flexible enough for broader ingestion, richer providers, and more advanced digestion strategies.
