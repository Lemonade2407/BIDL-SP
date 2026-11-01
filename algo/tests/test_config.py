"""Tests for model configuration validation."""
from __future__ import annotations

import pytest

from algo.adapter.config import ModelConfig


def test_defaults_match_reproduction_package() -> None:
    cfg = ModelConfig()
    assert cfg.size == 256
    assert cfg.in_ch == 3
    assert cfg.rgb is True
    assert cfg.tta is True
    assert cfg.scales == (1.0,)
    assert cfg.threshold == 0.5
    assert cfg.postproc is True
    assert cfg.min_area == 0.001


def test_from_dict_and_to_dict_roundtrip() -> None:
    cfg = ModelConfig.from_dict(
        {
            "size": 256,
            "in_ch": 3,
            "rgb": True,
            "scales": [1.0],
            "threshold": 0.4,
            "seed": 2,
        }
    )
    payload = cfg.to_dict()
    assert payload["scales"] == [1.0]
    assert payload["threshold"] == 0.4
    assert ModelConfig.from_dict(payload) == cfg


def test_multiscale_is_rejected() -> None:
    with pytest.raises(ValueError, match="fixed positional"):
        ModelConfig(scales=(0.75, 1.0, 1.25))


def test_invalid_threshold_and_area_gate() -> None:
    with pytest.raises(ValueError):
        ModelConfig(threshold=1.5)
    with pytest.raises(ValueError):
        ModelConfig(min_area=-0.1)


def test_overrides_validate() -> None:
    cfg = ModelConfig()
    overridden = cfg.with_overrides(tta=False, threshold=0.2, postproc=False)
    assert overridden.tta is False
    assert overridden.threshold == 0.2
    assert overridden.postproc is False
    with pytest.raises(ValueError):
        cfg.with_overrides(threshold=9)
