# Product Specification

## 1. Product Definition

Bookworm Digester is a document digestion system that ingests heterogeneous files, progressively reads their content through an LLM-guided loop, and emits agent-native skill directories for downstream tools such as Copilot, OpenCode, and Codex. The output is optimized for two audiences:

1. **humans** who need a fast map of the source material
2. **downstream LLM agents** that need high-signal context without paying to reread the original corpus

The central design principle is **context compression without losing decision-relevant meaning**.

## 2. Problem Statement

Raw documents are expensive for people and LLMs to consume:

- they are often long, repetitive, and heterogeneous
- useful facts are buried inside format-specific structures
- not every paragraph deserves to survive into downstream context windows
- a later agent often needs navigational context before reading details

Bookworm Digester solves this by converting source material into:

- a set of **section-like markdown skill files**
- a set of **agent-native skill directory trees** that make those skills directly loadable by supported agent tools

## 3. Goals

### 3.1 Primary Goals

1. Accept multiple source formats through one pipeline
2. Normalize them into a canonical internal representation
3. Use an LLM-guided loop that can decide whether more source material is needed
4. Produce concise markdown artifacts that preserve valuable context
5. Preserve enough provenance that claims can be traced back to inputs
6. Keep the system extensible for additional providers and source types

### 3.2 Secondary Goals

1. Offer both a CLI and a library API
2. Keep the implementation deterministic where LLM behavior is not required
3. Make it easy to integrate local/self-hosted models such as Ollama

## 4. Non-Goals for v1

1. OCR for scanned or image-based documents
2. Legacy `.doc` support
3. Real-time collaborative editing
4. Web UI or multi-user SaaS features
5. Persistent database-backed run management
6. Advanced retrieval or embedding infrastructure

## 5. Target Users

### 5.1 Engineering Agents

An engineering agent should be able to discover the generated `SKILL.md` files from its native skill root, use their descriptions to decide what to load, then read only the relevant skill bodies needed for a coding task.

### 5.2 Human Researchers or Analysts

A human should be able to scan the generated skill directories, open the most relevant skill files, and avoid reading full source files unless provenance indicates a deeper check is necessary.

### 5.3 Automation Pipelines

Other Python code should be able to call the library API to digest files as part of a larger workflow.

## 6. Supported Inputs

### 6.1 In Scope in Current Implementation

- plain text (`.txt`)
- markdown (`.md`)
- reStructuredText (`.rst`)
- PDF (`.pdf`)
- DOCX (`.docx`)
- Excel workbooks (`.xlsx`, `.xlsm`)

### 6.2 Out of Scope in Current Implementation

- scanned PDFs requiring OCR
- legacy Word `.doc`
- legacy Excel `.xls`
- image files
- audio/video inputs

## 7. Output Contract

### 7.1 Required Outputs

For each successful digestion run, the system must write three agent-targeted output directories by default:

1. **`copilot/.github/skills/<skill>/SKILL.md`**
2. **`opencode/.opencode/skills/<skill>/SKILL.md`**
3. **`codex/.agents/skills/<skill>/SKILL.md`**

### 7.2 Topic File Requirements

Each generated `SKILL.md` file must contain:

- a stable topic title
- YAML frontmatter with the skill name and explicit routing description
- when-to-use guidance generated from dedicated routing data instead of summary inference
- a concise purpose summary
- a list of durable, actionable core instructions
- workflow notes for using the skill safely with live repository context
- a list of source references

Each topic file should be independently useful as a reusable skill-style artifact for coding agents such as Codex, Claude Code, Copilot, and OpenCode.

### 7.3 Agent Export Layout Requirements

The agent export layer must:

- create one directory per supported agent target
- arrange each skill as `<agent-root>/<skill-name>/SKILL.md` beneath that tool's native discovery path
- preserve routing guidance in `SKILL.md` frontmatter descriptions and body content
- preserve source provenance inside each generated skill body

## 8. Functional Requirements

### FR-1 Ingest Multiple Source Types

The system must accept files and directories. For directories, it must process supported files contained inside them.

### FR-2 Normalize Extracted Content

All source formats must be normalized into a shared document model that includes:

- source identity
- section structure
- extracted text
- provenance

### FR-3 Chunk Input Incrementally

The system must split extracted sections into bounded chunks suitable for repeated LLM processing.

### FR-4 Maintain Topic State Across Iterations

The system must preserve a growing topic map across digestion batches so later prompts can build on earlier understanding.

### FR-5 Let the LLM Advise on Topic Continuation

For each batch, the provider must return:

- topic updates
- whether processing should continue
- rationale

The system may delay acting on provider completion hints until a configurable minimum number of batches has been processed.
`should_continue` applies to the currently visible topics, not to the entire remaining corpus. If chunks remain, the system must continue digesting them unless `max_batches` has been reached.

### FR-6 Finalize Topics for Export

Before writing markdown, the system must finalize or refine topic digests through the provider abstraction.
The finalization contract must preserve an explicit routing field plus structured workflow notes so exported skill files do not have to derive router text from summaries.

### FR-7 Preserve Source Traceability

Every topic must keep references back to the source material.

### FR-8 Support Swappable Providers

The digestion engine must not depend directly on a specific provider SDK outside the provider layer.

### FR-9 Offer a Public API

The system must expose a Python API that other code can call to process inputs and receive a structured result.

### FR-10 Offer a CLI

The system must expose a command-line entrypoint for batch usage.

## 9. Behavioral Requirements

### 9.1 Concision

Generated summaries must prefer high-value, reusable facts over verbose restatement.

### 9.2 Topic-Centric Organization

Output should be organized around section-like topics / skills, not around raw chunks or page order.

### 9.2.1 Agent-Skill Usability

Generated files should help coding agents decide what to read and how to act. The skill directory layout plus each `SKILL.md` description should behave as the router, while each skill file should state when to use it, what instructions matter, what workflow notes or caveats apply, and where to verify source provenance.

### 9.3 Provenance

Topic digests must retain enough provenance to let a human or downstream agent know where each topic came from.

### 9.4 Explicit Failure

Unsupported inputs, missing credentials, empty extraction, and empty model responses must fail explicitly.
Low-quality finalized skills must also fail explicitly instead of silently falling back to weaker pre-finalized output.

### 9.5 Controlled Coverage

The system must provide configuration knobs that let operators trade off:

- cost
- latency
- recall
- number of active topics kept in prompt context

## 10. CLI Requirements

The CLI must support:

```bash
bookworm digest INPUT [INPUT ...] --output-dir OUT --model MODEL
```

It must also accept:

- `--provider-kind`
- `--api-key-file`
- `--api-key-env`
- `--base-url`
- `--organization`
- `--ollama-host`
- `--ollama-port`
- `--max-chunk-chars`
- `--batch-size`
- `--minimum-batches-before-stop`
- `--max-batches`
- `--max-active-topics` (with `--max-topics` retained as a compatibility alias)

Hosted providers must load their API key from an environment variable (defaulting to `OPENAI_API_KEY`, with `--api-key-env` allowing an override) or from a file passed via `--api-key-file`. Raw API keys must not be accepted directly on the command line.

When `--provider-kind ollama` is selected, the CLI must:

- default the host to `127.0.0.1`
- default the port to `11434`
- allow both values to be overridden explicitly

When `--provider-kind mock-llm` is selected, the CLI must:

- require no API key
- require no network access
- return deterministic placeholder topics that preserve real source references for end-to-end validation

## 11. Library API Requirements

The library API must:

- accept input paths
- accept an output directory
- accept an injected provider implementation
- return a structured result containing documents, chunks, topics, stop reason, and artifact paths

## 12. Provider Contract

Any provider implementation must support two logical phases:

1. **batch digestion**
2. **topic finalization**

### 12.1 Batch Digestion Contract

Input:

- digest config
- batch number / total batches
- current chunk batch
- current topic map

Output:

- `topic_updates`
- `should_continue`
- `rationale`

The continuation decision answers: "do these visible topics likely continue into nearby chunks?" It does not authorize stopping before unseen chunks are processed.

### 12.2 Finalization Contract

Input:

- list of accumulated topics

Output:

- finalized list of topics suitable for markdown export as reusable skill files

## 13. Markdown Quality Requirements

Generated markdown should be:

- short enough for downstream LLM context efficiency
- specific enough to be actionable
- structured enough to support navigation
- free from unnecessary boilerplate

The output should preserve:

- durable facts
- architectural implications
- terminology
- decisions
- constraints

The output should avoid:

- repetitive paraphrase
- low-signal filler
- chunk-by-chunk restatement
- unsupported speculation

## 14. Configuration Requirements

The initial implementation must support configuration of:

- chunk size by characters
- chunks per provider batch
- minimum batches before early stopping
- maximum batches
- maximum active topics kept in prompt context
- provider kind
- model name
- credential inputs

## 15. Acceptance Criteria

The system is considered acceptable when it can:

1. Ingest at least one supported input file
2. Normalize it successfully
3. Produce one or more chunks
4. Call the provider through the abstract interface
5. Accumulate at least one topic
6. Write skill-file markdown outputs in supported agent-native layouts
7. Emit the default Copilot, OpenCode, and Codex export trees
8. Expose the same core behavior through CLI and library API

## 16. Quality Attributes

### 16.1 Extensibility

Adding a new source type should require a new adapter plus registry registration, not a redesign of the orchestrator.

Adding a new provider should require a new provider class plus factory integration, not a rewrite of the digest loop.

### 16.2 Maintainability

The codebase should separate:

- extraction concerns
- prompt/provider concerns
- orchestration concerns
- output rendering concerns

### 16.3 Traceability

Every topic should be able to point back to source material through structured references.

### 16.4 Cost Awareness

Operators should be able to reduce provider usage by shrinking chunk sizes, batch counts, or active topic counts.

### 16.5 Deterministic Core

All non-LLM behaviors such as file loading, chunking, adapter routing, and markdown layout should be deterministic.

## 17. Operational Constraints

### 17.1 Runtime

- Python 3.8+

### 17.2 Dependencies

- `openai`
- `pypdf`
- `python-docx`
- `openpyxl`
- `pytest` for development

### 17.3 Environment

The provider runtime depends on external credentials or a compatible local model server.

## 18. Risks and Limitations

1. Provider output quality can vary by model
2. Character-based chunking is an approximation for token usage
3. PDF extraction quality depends on embedded text availability
4. Spreadsheet linearization can lose some relational nuance
5. OpenAI-compatible endpoints can vary in their compliance with JSON output expectations

## 19. Future Specification Candidates

Potential future revisions may add:

1. OCR support
2. legacy document adapters
3. richer citation formatting
4. structured JSON artifact output alongside markdown
5. retry policies and resilience controls
6. richer prioritization logic for which chunks to read next
7. run manifests, coverage metrics, and telemetry

Ollama local backend support is included in the current implementation baseline.

## 20. Product Summary

Bookworm Digester is specified as a **multi-format, LLM-guided context compressor**. Its value comes from turning long and messy source material into a small graph of markdown references that can be efficiently consumed by later humans or agents. The current implementation already satisfies the core v1 shape:

- pluggable source ingestion
- adaptive digestion loop
- provider abstraction
- concise markdown outputs
- agent-native skill directory exports
