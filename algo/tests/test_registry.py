"""Tests for the local model registry."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from algo.adapter.registry import ModelRegistry, sha256_file


def test_registry_contains_three_seeds() -> None:
    registry = ModelRegistry()
    models = registry.all()
    assert len(models) == 3
    assert {m.version for m in models} == {
        "s256rgb-seed0",
        "s256rgb-seed1",
        "s256rgb-seed2",
    }


def test_active_model_is_seed0() -> None:
    registry = ModelRegistry()
    active = registry.active()
    assert active.version == "s256rgb-seed0"
    assert active.config.seed == 0
    assert active.metric_dice == pytest.approx(0.7240, abs=1e-6)


def test_lookup_by_id_and_version() -> None:
    registry = ModelRegistry()
    assert registry.get("s256rgb-seed1").config.seed == 1
    assert registry.get("mv-transunet-s256rgb-seed2").config.seed == 2
    assert registry.get("transunet/s256rgb-seed0").config.seed == 0


def test_unknown_model_raises() -> None:
    registry = ModelRegistry()
    with pytest.raises(Exception):
        registry.get("does-not-exist")


def test_sha256_file(tmp_path: Path) -> None:
    path = tmp_path / "x.bin"
    path.write_bytes(b"bidlsp")
    assert sha256_file(path) == "7d7ee1029144bb9482ad61a59b5f370c7b48e4cc60a2590bb49344fa59d01e8b"


def test_registered_weight_integrity() -> None:
    registry = ModelRegistry()
    model = registry.active()
    if not model.weights_path.exists():
        pytest.skip("published weights are not present in this workspace")
    check = registry.verify_weight(model.id)
    assert check["status"] == "PASS"


def test_activate_and_rollback(tmp_path: Path) -> None:
    source = ModelRegistry().path
    target = tmp_path / "registry.json"
    shutil.copy(source, target)

    registry = ModelRegistry(target)
    assert registry.active().version == "s256rgb-seed0"

    registry.activate("s256rgb-seed1")
    reloaded = ModelRegistry(target)
    assert reloaded.active().version == "s256rgb-seed1"
    assert reloaded.get("s256rgb-seed0").status == "archived"
    assert reloaded.get("s256rgb-seed2").status == "candidate"

    reloaded.activate("mv-transunet-s256rgb-seed0")
    assert ModelRegistry(target).active().version == "s256rgb-seed0"
