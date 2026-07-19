import pytest

from digester.core.presets import resolve_preset


def test_local_26b_preset_uses_conservative_defaults() -> None:
    preset = resolve_preset("local-26b")

    assert preset.batch_size == 1
    assert preset.max_chunk_tokens == 1024
    assert preset.max_active_topics == 6
    assert preset.digest_temperature == 0.15
    assert preset.finalize_temperature == 0.0


def test_frontier_preset_and_individual_overrides_are_reproducible() -> None:
    preset = resolve_preset("frontier", batch_size=3, max_chunk_tokens=1536)

    assert preset.batch_size == 3
    assert preset.max_chunk_tokens == 1536
    assert preset.context_window_tokens == 128000
    assert preset.metadata()["name"] == "frontier"


def test_legacy_preset_preserves_previous_defaults() -> None:
    preset = resolve_preset("legacy")

    assert preset.batch_size == 2
    assert preset.max_chunk_tokens is None
    assert preset.digest_temperature == 0.4
    assert preset.max_active_topics == 12


def test_unknown_preset_and_override_fail_explicitly() -> None:
    with pytest.raises(ValueError, match="Unknown model preset"):
        resolve_preset("missing")
    with pytest.raises(ValueError, match="Unknown preset override"):
        resolve_preset("legacy", invented=True)
