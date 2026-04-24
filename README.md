# Bookworm Digester

Bookworm Digester ingests source documents, incrementally digests them through an LLM-guided loop, and emits section-like skill files plus an `INDEX.md` for downstream human or agent workflows.

Each output file is meant to behave like a reusable skill/topic for another agent: focused enough to stand alone, but still traceable back to the source material.

## Supported inputs

- Plain text and markdown
- PDF
- DOCX
- XLSX/XLSM

## Provider model

- `openai`: hosted OpenAI models
- `openai-compatible`: local or self-hosted models that expose an OpenAI-compatible API
- `ollama`: local Ollama server via `http://<host>:<port>/api/chat`

## CLI example

```bash
bookworm digest docs/*.txt \
  --output-dir out \
  --provider-kind openai \
  --model gpt-4.1-mini \
  --api-key "$OPENAI_API_KEY" \
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

## Loop semantics

The digester always keeps processing remaining chunks unless it hits `--max-batches`. The provider's `should_continue` flag is narrower: it tells the orchestrator whether the **currently visible** section-like topics likely continue into adjacent chunks, not whether the whole corpus is finished. That lets Bookworm export many skill files from long documents instead of stopping early after a few seemingly complete topics.
