"""Offline evaluation adapter around the frozen ``eval_postproc.py`` protocol.

Evaluation is intentionally executed as a subprocess, not reimplemented:
the published numbers (A2+A1 / A2+A1+A3) come from that exact script, and
running it keeps the platform and the reproduction package on one口径.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from ..adapter.errors import EvaluationError
from ..adapter.paths import TRANSUNET_CODE_DIR, TRANSUNET_DIR
from ..adapter.registry import ModelRegistry, ModelVersion

_VARIANTS = ("baseline", "A2_tta", "A2+A1", "A2+A1+A3")


def _sanitize_tag(tag: str) -> str:
    tag = re.sub(r"[^A-Za-z0-9._-]+", "_", str(tag)).strip("._-")
    return tag or "platform_eval"


def _tail(text: str, limit: int = 4000) -> str:
    text = (text or "").strip()
    return text[-limit:]


def summarize_eval_data(data: dict[str, Any]) -> dict[str, Any]:
    """Pick the variants the platform registers from an eval_postproc JSON."""
    variants = data.get("variants") or {}
    selected: dict[str, Any] = {}
    for name in _VARIANTS:
        if name not in variants:
            continue
        item = variants[name] or {}
        selected[name] = {
            "threshold": item.get("threshold"),
            "postproc": item.get("postproc"),
            "agg": item.get("agg") or {},
        }
    return selected


def compare_with_registry(
    model: ModelVersion,
    metrics: dict[str, Any],
    *,
    tolerance: float = 1e-3,
) -> dict[str, Any]:
    """Compare the rerun A2+A1 Dice with the registered value."""
    expected = None
    try:
        expected = float(model.metrics["A2+A1"]["dice"])
    except (KeyError, TypeError, ValueError):
        pass

    actual = None
    try:
        actual = float(metrics["A2+A1"]["agg"]["dice_lesion"])
    except (KeyError, TypeError, ValueError):
        pass

    if expected is None or actual is None:
        return {
            "result": "SKIPPED",
            "reason": "registered or rerun A2+A1 Dice is missing",
            "expected_dice": expected,
            "actual_dice": actual,
            "tolerance": tolerance,
        }

    delta = actual - expected
    return {
        "result": "PASS" if abs(delta) <= tolerance else "FAIL",
        "expected_dice": expected,
        "actual_dice": actual,
        "delta": delta,
        "tolerance": tolerance,
        "variant": "A2+A1",
    }


@dataclass
class EvaluationReport:
    model_id: str
    model_version: str
    out_tag: str
    json_path: str
    metrics: dict[str, Any]
    regression: dict[str, Any]
    elapsed_sec: float
    command: list[str] = field(default_factory=list)
    stdout_tail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": {"id": self.model_id, "version": self.model_version},
            "out_tag": self.out_tag,
            "json_path": self.json_path,
            "metrics": self.metrics,
            "regression": self.regression,
            "elapsed_sec": round(float(self.elapsed_sec), 2),
            "command": self.command,
            "stdout_tail": self.stdout_tail,
        }


def build_eval_command(model: ModelVersion, out_tag: str) -> list[str]:
    """Build the exact ``eval_postproc.py`` command for a registered model."""
    cfg = model.config
    cmd = [
        sys.executable,
        "-u",
        "eval_postproc.py",
        "--ckpt",
        str(model.weights_path),
        "--model",
        model.name,
        "--size",
        str(cfg.size),
        "--rgb" if cfg.rgb else "--gray",
        "--seed",
        str(cfg.seed),
        "--scales",
        ",".join(str(float(x)) for x in cfg.scales),
        "--min-area",
        str(cfg.min_area),
        "--out-tag",
        out_tag,
    ]
    if cfg.tta:
        cmd.append("--tta")
    return cmd


def run_evaluation(
    model_version: str | ModelVersion,
    *,
    registry: ModelRegistry | None = None,
    out_tag: str | None = None,
    timeout: int = 7200,
    device: str = "auto",
    tolerance: float = 1e-3,
    verify_weight: bool = True,
) -> EvaluationReport:
    """Run ``eval_postproc.py`` and return selected metrics + regression status."""
    reg = registry or ModelRegistry()
    model = reg.get(model_version) if not isinstance(model_version, ModelVersion) else model_version
    if verify_weight:
        check = reg.verify_weight(model.id)
        if check["status"] != "PASS":
            raise EvaluationError(
                f"weight verification failed before evaluation: {check['status']}",
                details=[check],
            )

    cfg = model.config
    tag = _sanitize_tag(out_tag or f"platform_{model.version}")
    cmd = build_eval_command(model, tag)

    env = os.environ.copy()
    env["PYTHONPATH"] = str(TRANSUNET_CODE_DIR) + os.pathsep + env.get("PYTHONPATH", "")
    if str(device).lower() == "cpu":
        env["CUDA_VISIBLE_DEVICES"] = ""

    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(TRANSUNET_CODE_DIR),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise EvaluationError(
            f"evaluation timed out after {timeout}s",
            details=[{"command": cmd, "stdout_tail": _tail(exc.stdout or "")}],
        ) from exc
    elapsed = time.perf_counter() - started

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""
    if proc.returncode != 0:
        raise EvaluationError(
            f"eval_postproc.py exited with code {proc.returncode}",
            details=[{"command": cmd, "stdout_tail": _tail(stdout + "\n" + stderr)}],
        )

    json_path = TRANSUNET_DIR / "results" / f"{tag}_seed{cfg.seed}.json"
    if not json_path.exists():
        raise EvaluationError(
            f"evaluation JSON not found: {json_path}",
            details=[{"stdout_tail": _tail(stdout)}],
        )

    data = json.loads(json_path.read_text(encoding="utf-8"))
    metrics = summarize_eval_data(data)
    regression = compare_with_registry(model, metrics, tolerance=tolerance)
    return EvaluationReport(
        model_id=model.id,
        model_version=model.version,
        out_tag=tag,
        json_path=str(json_path.resolve()),
        metrics=metrics,
        regression=regression,
        elapsed_sec=elapsed,
        command=cmd,
        stdout_tail=_tail(stdout),
    )


def verify_metrics(*, timeout: int = 600) -> dict[str, Any]:
    """Run ``transunet/scripts/verify_metrics.py`` and parse RESULT."""
    cmd = [sys.executable, "-u", "scripts/verify_metrics.py"]
    started = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(TRANSUNET_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise EvaluationError(
            f"verify_metrics.py timed out after {timeout}s",
            details=[{"stdout_tail": _tail(exc.stdout or "")}],
        ) from exc

    output = (proc.stdout or "") + ("\n" + proc.stderr if proc.stderr else "")
    status = "PASS" if "RESULT: PASS" in output else "FAIL"
    return {
        "status": status,
        "returncode": proc.returncode,
        "elapsed_sec": round(time.perf_counter() - started, 2),
        "command": cmd,
        "stdout": output,
    }
