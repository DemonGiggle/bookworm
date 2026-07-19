from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Dict, Optional


@dataclass(frozen=True)
class ModelPreset:
    name: str
    batch_size: int
    max_chunk_tokens: Optional[int]
    context_window_tokens: Optional[int]
    reserved_context_tokens: int
    max_active_topics: int
    max_active_topic_tokens: int
    digest_temperature: float
    finalize_temperature: float
    finalize_max_output_tokens: int

    def metadata(self) -> Dict[str, object]:
        return asdict(self)


PRESETS = {
    "legacy": ModelPreset("legacy", 2, None, None, 4096, 12, 12000, 0.4, 0.1, 4096),
    "local-26b": ModelPreset("local-26b", 1, 1024, 32768, 8192, 6, 6000, 0.15, 0.0, 4096),
    "frontier": ModelPreset("frontier", 2, 2048, 128000, 16384, 12, 12000, 0.3, 0.1, 8192),
}


def resolve_preset(name: str, **overrides: object) -> ModelPreset:
    if name not in PRESETS:
        raise ValueError("Unknown model preset: {name}".format(name=name))
    values = {key: value for key, value in overrides.items() if value is not None}
    unknown = set(values) - set(ModelPreset.__dataclass_fields__)
    if unknown:
        raise ValueError(
            "Unknown preset override(s): {names}".format(
                names=", ".join(sorted(unknown))
            )
        )
    values.pop("name", None)
    return replace(PRESETS[name], **values)
