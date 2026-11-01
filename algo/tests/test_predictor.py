"""Slow integration test: adapter output must match the recorded A2+A1 metric.

Set ``RUN_SLOW_TESTS=1`` to enable. It loads the 421 MB seed-0 weight and runs
TTA inference on one test image, so it takes tens of seconds on CPU.
"""
from __future__ import annotations

import json
import os

import pytest

from algo.adapter.metrics import dice_binary, load_busi_index, load_reference_mask
from algo.adapter.paths import TRANSUNET_DIR
from algo.adapter.predictor import Predictor
from algo.adapter.registry import ModelRegistry


def _require_slow() -> None:
    if os.environ.get("RUN_SLOW_TESTS") != "1":
        pytest.skip("set RUN_SLOW_TESTS=1 to run the slow inference test")


def test_predictor_matches_recorded_a2_a1_dice() -> None:
    _require_slow()
    pytest.importorskip("torch")

    registry = ModelRegistry()
    model = registry.active()
    if not model.weights_path.exists():
        pytest.skip("published weights are not present in this workspace")

    split = json.loads((TRANSUNET_DIR / "data" / "splits" / "busi_seed0.json").read_text())
    name = split["test"][0]
    item = next(it for it in load_busi_index() if it["name"] == name)
    gt = load_reference_mask(item)

    predictor = Predictor(model, device="cpu")
    prediction = predictor.predict_path(item["image"])
    assert prediction.mask.shape == gt.shape
    assert 0.0 <= prediction.prob_mean <= 1.0
    assert prediction.mask.dtype == bool
    assert prediction.mask_raw.shape == gt.shape

    recorded_path = TRANSUNET_DIR / "results" / "postproc_p1_transunet_s256rgb_seed0.json"
    recorded = json.loads(recorded_path.read_text())
    per_image = recorded["variants"]["A2+A1"]["per_image"]
    expected = next(row["dice"] for row in per_image if row["name"] == name)

    actual = dice_binary(prediction.mask, gt)
    assert actual == pytest.approx(expected, abs=1e-3)

    payload = prediction.to_dict()
    assert payload["result"]["mask_rle"]["size"] == [gt.shape[0], gt.shape[1]]
    assert payload["model"]["version"] == "s256rgb-seed0"
