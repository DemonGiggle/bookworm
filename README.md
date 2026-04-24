# Bookworm Digester

Bookworm Digester ingests source documents, incrementally digests them through an LLM-guided loop, and emits concise topic-centric markdown artifacts plus an `INDEX.md` for downstream human or agent workflows.

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
  --api-key "$OPENAI_API_KEY"
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
