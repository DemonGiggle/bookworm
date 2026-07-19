# Benchmark suite

The corpus is synthetic, contains no private material, and is released under CC0-1.0. Its manifest is versioned separately from the result schema so results can be compared only when both revisions match.

Run the deterministic CI-sized comparison:

```bash
python -m digester.benchmark --output-dir benchmark-results
```

Run real local and frontier candidates against the identical corpus:

```bash
python -m digester.benchmark \
  --candidate local:ollama:gemma4:26b:local-26b \
  --candidate frontier:openai:gpt-4.1:frontier \
  --output-dir benchmark-results
```

Provider credentials and endpoints use the same environment/configuration as normal Bookworm runs. Each candidate is `NAME:PROVIDER:MODEL:PRESET`; repeat `--candidate` to compare tiers. The command performs two runs by default to measure slug stability and writes `results.json` plus `report.md`.

Correctness and provenance scores are kept separate from prose-style statistics. Operational token/cost fields remain `null` when a provider does not expose usage. The deterministic mock run validates the harness in CI; full model runs are optional and should not be treated as comparable unless the code commit, corpus revision, and parameters match.
