# Bookworm Digester

Bookworm Digester ingests source documents, incrementally digests them through an LLM-guided loop, and writes completed section-like skill files into agent-native skill directories for downstream Copilot, OpenCode, and Codex workflows.

Each output file is meant to behave like a reusable skill file for another agent: focused enough to stand alone, but still traceable back to the source material.

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
  --ollama-port 11434
```

If `--ollama-port` is omitted, the CLI defaults to port `11434`.

## MockLLM example

```bash
bookworm digest docs/*.txt \
  --output-dir out \
  --provider-kind mock-llm \
  --model fake-model
```

`mock-llm` does not require an API key and intentionally produces synthetic placeholder topics from source metadata so you can validate ingestion, orchestration, and artifact export flows quickly.

## Loop semantics

The digester always keeps processing remaining chunks unless it hits `--max-batches`. The provider's `should_continue` flag is narrower: it tells the orchestrator whether the **currently visible** section-like topics likely continue into adjacent chunks, not whether the whole corpus is finished. When the provider marks the visible cluster complete, Bookworm finalizes and writes those topic files immediately, then continues scanning later chunks for new topics. That keeps long runs from holding every completed topic in memory until the very end.
