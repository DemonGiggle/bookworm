# Configuration Reference

Bookworm reads optional defaults from `~/.local/bookworm/config.toml`. All settings belong in a single `[digest]` table and use the snake_case form of their CLI option names.

```toml
[digest]
provider_kind = "opencode-go"
model = "kimi-k2.6"
output_dir = "./out"
api_key_env = "OPENCODE_API_KEY"
```

Input files and directories remain positional command-line arguments:

```bash
bookworm digest docs/
```

## Precedence

Settings resolve in this order, from highest to lowest priority:

1. Explicit command-line options
2. Values in `~/.local/bookworm/config.toml`
3. Supported environment-backed defaults
4. The selected preset and built-in defaults

For example, `--model kimi-k3` overrides `model = "kimi-k2.6"` for one run. Unknown sections, unknown keys, invalid types, and conflicting settings are rejected instead of ignored.

TOML has no `null` value. Omit an optional setting when it should be unset.

## General settings

| Setting | Type and default | Description |
| --- | --- | --- |
| `output_dir` | String; required from TOML or CLI | Directory beneath which Bookworm writes the Copilot, OpenCode, and Codex artifact trees. |
| `recursive` | Boolean; `false` | Recursively scan nested directories supplied as positional inputs. |
| `preset` | String; `"legacy"` | Selects a coordinated set of chunking, context, topic-state, temperature, and finalization-budget defaults. See [Presets](#presets). |
| `minimum_batches_before_stop` | Integer; `2` | Minimum number of processed batches before Bookworm may finalize an active topic cluster at a detected source, heading, topic-count, or token boundary. It does not stop ingestion of the remaining corpus. |
| `max_batches` | Integer; `50` | Hard cap on processed batches. If the corpus contains more, the result reports that the cap was reached. |

## Primary provider

| Setting | Type and default | Description |
| --- | --- | --- |
| `provider_kind` | String; `"openai"` | Primary text provider: `openai`, `openai-compatible`, `opencode-go`, `ollama`, or `mock-llm`. |
| `model` | String; required from TOML or CLI | Model ID sent to the primary provider. OpenCode Go accepts raw IDs such as `kimi-k2.6` and prefixed IDs such as `opencode-go/kimi-k2.6`. |
| `finalize_review_model` | String; unset | Optional separate model for the evidence-grounding review after initial finalization. This is currently useful for OpenCode Go, which always performs one review pass; when omitted, its primary model reviews its own result. A separate model adds latency and usage. |
| `base_url` | String; `DIGESTER_BASE_URL` or empty | API base URL for `openai-compatible`. Native OpenAI and OpenCode Go select their own endpoints. |
| `organization` | String; `OPENAI_ORG_ID` or empty | Optional OpenAI organization ID. |
| `ollama_host` | String; `OLLAMA_HOST` or `"127.0.0.1"` | Ollama host used by an Ollama primary provider or image analyzer. |
| `ollama_port` | Integer; `OLLAMA_PORT` or `11434` | Ollama server port. |
| `timeout_sc` | Integer; unset | Optional Ollama request timeout in seconds. An omitted value means no configured timeout. |

## Credentials

Bookworm intentionally does not accept a raw API key as a TOML value. Configure an environment-variable name or a key-file path instead.

| Setting | Type and default | Description |
| --- | --- | --- |
| `api_key_env` | String; provider-dependent | Name of the environment variable containing the primary provider key. The default name is `OPENCODE_API_KEY` for OpenCode Go and `OPENAI_API_KEY` otherwise. The value is a variable name, not the key itself. |
| `api_key_file` | String; unset | Path to a file containing only the primary API key. Mutually exclusive with `api_key_env`. |
| `image_api_key_env` | String; provider-dependent | Name of the environment variable containing an image-provider key when image analysis uses separate credentials. |
| `image_api_key_file` | String; unset | Path to a file containing only the image-provider key. Mutually exclusive with `image_api_key_env`. |

Example using an environment variable:

```toml
[digest]
api_key_env = "OPENCODE_API_KEY"
```

```bash
export OPENCODE_API_KEY="your-actual-api-key"
```

Example using a protected key file:

```toml
[digest]
api_key_file = "/home/you/.local/bookworm/opencode.key"
```

Use only one member of each `*_key_env`/`*_key_file` pair.

## Embedded-image analysis

| Setting | Type and default | Description |
| --- | --- | --- |
| `image_analyzer_kind` | String; unset | Enables image analysis with `openai`, `openai-compatible`, `opencode-go`, `ollama`, or `mock-image`. When omitted, supported documents are ingested without analyzing embedded images. |
| `image_analyzer_model` | String; primary `model` | Model ID used for image analysis. Set it explicitly when the primary text model is not vision-capable. |
| `image_capability` | `"vision"` or `"text-only"`; unset | Optional safety declaration. Selecting an image analyzer already implies `vision`. Setting `text-only` rejects the configuration before requests are sent, so this can normally be omitted. |
| `image_temperature` | Number; `BOOKWORM_IMAGE_TEMPERATURE` or `0.0` | Sampling temperature for image descriptions. Lower values favor repeatability. |

If image-specific credentials are omitted, Bookworm uses explicit primary credential options when present; otherwise it resolves the default environment variable for the image provider.

## Generation settings

| Setting | Type and default | Description |
| --- | --- | --- |
| `digest_temperature` | Number; preset value | Sampling temperature for incremental topic extraction and merging. Lower values generally produce more stable topic structure. `BOOKWORM_DIGEST_TEMPERATURE` supplies an environment-backed default. |
| `finalize_temperature` | Number; preset value | Sampling temperature for final skill rewriting and grounding. `BOOKWORM_FINALIZE_TEMPERATURE` supplies an environment-backed default. |
| `finalize_max_output_tokens` | Integer; preset value | Maximum completion-token allowance for each topic finalization request. Reasoning models may need the larger frontier value. |

## Chunking, context, and active state

| Setting | Type and default | Description |
| --- | --- | --- |
| `max_chunk_chars` | Integer; `1800` | Character ceiling for each source chunk. Oversized paragraphs and unbroken text are hard-split. |
| `max_chunk_tokens` | Integer; preset value or unset | Token ceiling for each chunk, estimated conservatively. When both character and token limits exist, both are enforced. |
| `context_window_tokens` | Integer; preset value or unset | Model context-window size used to calculate a safe per-chunk budget. |
| `reserved_context_tokens` | Integer; preset value | Context reserved for prompts, active topic state, and output. It must be smaller than `context_window_tokens` when a context window is configured. |
| `batch_size` | Integer; preset value | Number of chunks sent in each digest request. Larger batches reduce request count but consume more context. |
| `max_active_topics` | Integer; preset value | Maximum recent topics included in each digest prompt. `max_topics` is only a CLI compatibility alias; use `max_active_topics` in TOML. |
| `max_active_topic_tokens` | Integer; preset value | Maximum estimated token size of the accumulated active-topic state before Bookworm finalizes the cluster and starts a fresh one. |

Explicit TOML or CLI values for preset-controlled settings override the selected preset.

## Logging

| Setting | Type and default | Description |
| --- | --- | --- |
| `verbose` | Boolean; `false` | Emit organized, truncated request and response diagnostics. Mutually exclusive with `vv` when true. |
| `vv` | Boolean; `false` | Emit full request and response bodies without omitting the middle. This can expose source content in logs. Mutually exclusive with `verbose` when true. |
| `log_location` | String; `"stdio"` | `stdio` writes progress and diagnostics to standard streams. Any other value is treated as a log-file path whose parent directories are created automatically. |

## Presets

| Setting | `legacy` | `local-26b` | `frontier` |
| --- | ---: | ---: | ---: |
| `batch_size` | 2 | 1 | 2 |
| `max_chunk_tokens` | unset | 1,024 | 2,048 |
| `context_window_tokens` | unset | 32,768 | 128,000 |
| `reserved_context_tokens` | 4,096 | 8,192 | 16,384 |
| `max_active_topics` | 12 | 6 | 12 |
| `max_active_topic_tokens` | 12,000 | 6,000 | 12,000 |
| `digest_temperature` | 0.4 | 0.15 | 0.1 |
| `finalize_temperature` | 0.1 | 0.0 | 0.1 |
| `finalize_max_output_tokens` | 4,096 | 4,096 | 8,192 |

- Use `legacy` for backward-compatible behavior without a declared context window.
- Use `local-26b` for conservative local-model requests.
- Use `frontier` for larger hosted-model contexts and reasoning-model finalization budgets.

## Mutually exclusive settings

These pairs cannot both be enabled or populated in the same configuration:

- `api_key_env` and `api_key_file`
- `image_api_key_env` and `image_api_key_file`
- `verbose` and `vv` when both are `true`

An explicit CLI option can replace the other member of a configured pair for one run. For example, `--api-key-env TEMP_KEY` overrides a configured `api_key_file`.
