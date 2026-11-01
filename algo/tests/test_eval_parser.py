"""Tests for the offline evaluation parser and regression comparison."""
from __future__ import annotations

import json
import subprocess

import pytest

from algo.adapter.registry import ModelRegistry
from algo.worker import eval_worker as ew
from algo.worker.eval_worker import (
    build_eval_command,
    compare_with_registry,
    summarize_eval_data,
)


def test_summarize_selects_known_variants() -> None:
    data = {
        "variants": {
            "baseline": {"threshold": 0.5, "postproc": False, "agg": {"dice_lesion": 0.7}},
            "A2_tta": {"threshold": 0.5, "postproc": False, "agg": {"dice_lesion": 0.71}},
            "A2+A1": {"threshold": 0.5, "postproc": True, "agg": {"dice_lesion": 0.72}},
            "A2+A1+A3": {"threshold": 0.15, "postproc": True, "agg": {"dice_lesion": 0.73}},
            "unknown": {"threshold": 0.5, "postproc": False, "agg": {}},
        }
    }
    selected = summarize_eval_data(data)
    assert set(selected) == {"baseline", "A2_tta", "A2+A1", "A2+A1+A3"}
    assert selected["A2+A1"]["agg"]["dice_lesion"] == 0.72
    assert selected["A2+A1+A3"]["threshold"] == 0.15


def test_compare_regression_pass_and_fail() -> None:
    model = ModelRegistry().active()
    passing = {"A2+A1": {"agg": {"dice_lesion": 0.7241}}}
    result = compare_with_registry(model, passing, tolerance=1e-3)
    assert result["result"] == "PASS"
    assert result["delta"] == pytest.approx(0.0001, abs=1e-6)

    failing = {"A2+A1": {"agg": {"dice_lesion": 0.60}}}
    result = compare_with_registry(model, failing, tolerance=1e-3)
    assert result["result"] == "FAIL"


def test_compare_regression_skipped_without_metrics() -> None:
    model = ModelRegistry().active()
    result = compare_with_registry(model, {}, tolerance=1e-3)
    assert result["result"] == "SKIPPED"


def test_build_eval_command_matches_frozen_protocol() -> None:
    model = ModelRegistry().active()
    cmd = build_eval_command(model, "demo_tag")
    assert cmd[cmd.index("--ckpt") + 1] == str(model.weights_path)
    assert cmd[cmd.index("--model") + 1] == "transunet"
    assert cmd[cmd.index("--size") + 1] == "256"
    assert "--rgb" in cmd
    assert "--tta" in cmd
    assert cmd[cmd.index("--scales") + 1] == "1.0"
    assert cmd[cmd.index("--min-area") + 1] == "0.001"
    assert cmd[cmd.index("--out-tag") + 1] == "demo_tag"


def test_run_evaluation_with_mocked_subprocess(tmp_path, monkeypatch) -> None:
    model = ModelRegistry().active()
    registry = ModelRegistry()
    monkeypatch.setattr(
        registry, "verify_weight", lambda *a, **k: {"status": "PASS"}
    )
    monkeypatch.setattr(ew, "TRANSUNET_DIR", tmp_path)
    monkeypatch.setattr(ew, "TRANSUNET_CODE_DIR", tmp_path)
    results = tmp_path / "results"
    results.mkdir()

    def fake_run(cmd, **kwargs):  # noqa: ANN001
        payload = {
            "variants": {
                "baseline": {"threshold": 0.5, "postproc": False, "agg": {"dice_lesion": 0.70}},
                "A2+A1": {"threshold": 0.5, "postproc": True, "agg": {"dice_lesion": 0.724}},
                "A2+A1+A3": {"threshold": 0.15, "postproc": True, "agg": {"dice_lesion": 0.7318}},
            }
        }
        (results / "demo_seed0.json").write_text(json.dumps(payload))
        return subprocess.CompletedProcess(cmd, 0, stdout="ok", stderr="")

    monkeypatch.setattr(ew.subprocess, "run", fake_run)
    report = ew.run_evaluation(model, registry=registry, out_tag="demo", timeout=1, device="cpu")
    assert report.metrics["A2+A1"]["agg"]["dice_lesion"] == 0.724
    assert report.regression["result"] == "PASS"
    assert report.json_path.endswith("demo_seed0.json")
