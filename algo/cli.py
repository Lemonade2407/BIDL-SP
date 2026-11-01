"""Command-line interface for the BIDL-SP algorithm service.

Examples::

    python -m algo.cli models
    python -m algo.cli verify
    python -m algo.cli predict --image "transunet/data/Dataset_BUSI_with_GT/benign/benign (1).png"
    python -m algo.cli evaluate --model s256rgb-seed0
    python -m algo.cli verify-metrics
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from .adapter.errors import AlgoError
from .adapter.paths import OUTPUT_DIR
from .adapter.predictor import get_predictor
from .adapter.registry import ModelRegistry
from .worker.eval_worker import run_evaluation, verify_metrics


def _registry(args: argparse.Namespace) -> ModelRegistry:
    return ModelRegistry(getattr(args, "registry", None))


def _print_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def cmd_models(args: argparse.Namespace) -> int:
    registry = _registry(args)
    rows = []
    for model in registry.all():
        rows.append(
            {
                "id": model.id,
                "name": model.name,
                "version": model.version,
                "status": model.status,
                "dice_A2+A1": model.metric_dice,
                "weights_exists": model.weights_path.exists(),
                "weights_path": str(model.weights_path),
            }
        )
    if args.json:
        _print_json({"data": rows})
        return 0

    print(f"{'ID':32s} {'VERSION':20s} {'STATUS':10s} {'Dice':>7s}  WEIGHTS")
    for row in rows:
        dice = "-" if row["dice_A2+A1"] is None else f"{row['dice_A2+A1']:.4f}"
        exists = "ok" if row["weights_exists"] else "missing"
        print(
            f"{row['id']:32s} {row['version']:20s} {row['status']:10s} "
            f"{dice:>7s}  {exists}"
        )
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    registry = _registry(args)
    checks = registry.verify_all(recompute=not args.no_recompute)
    failed = [c for c in checks if c["status"] in ("FAIL", "MISSING")]
    payload: dict[str, Any] = {
        "status": "FAIL" if failed else "PASS",
        "checks": checks,
    }
    if failed:
        payload["failed"] = failed
    _print_json(payload)
    return 1 if failed else 0


def cmd_activate(args: argparse.Namespace) -> int:
    registry = _registry(args)
    active = registry.activate(args.model)
    _print_json(
        {
            "status": "PASS",
            "active": {
                "id": active.id,
                "name": active.name,
                "version": active.version,
                "status": active.status,
            },
        }
    )
    return 0


def cmd_predict(args: argparse.Namespace) -> int:
    image_path = Path(args.image)
    if not image_path.exists():
        raise AlgoError(f"image not found: {image_path}", code="INFERENCE_FAILED")

    predictor = get_predictor(
        args.model, device=args.device, registry=_registry(args)
    )
    prediction = predictor.predict_path(
        image_path,
        tta=args.tta,
        threshold=args.threshold,
        postproc=args.postproc,
        min_area=args.min_area,
    )

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_dir = OUTPUT_DIR / f"{stamp}-{image_path.stem}"
    task_id = str(uuid.uuid4())
    saved = prediction.save(
        out_dir, metadata={"task_id": task_id, "status": "succeeded"}
    )
    _print_json(saved)
    return 0


def cmd_evaluate(args: argparse.Namespace) -> int:
    report = run_evaluation(
        args.model,
        registry=_registry(args),
        out_tag=args.out_tag,
        timeout=args.timeout,
        device=args.device,
        tolerance=args.tolerance,
    )
    _print_json({"status": "succeeded", **report.to_dict()})
    return 3 if report.regression.get("result") == "FAIL" else 0


def cmd_verify_metrics(args: argparse.Namespace) -> int:
    result = verify_metrics(timeout=args.timeout)
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        result["output_path"] = str(output.resolve())
    _print_json(result)
    return 0 if result["status"] == "PASS" else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m algo.cli",
        description="BIDL-SP 算法服务：模型注册、单图推理、离线评估、指标回归",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("models", help="列出注册模型")
    p.add_argument("--registry", help="registry.json 路径")
    p.add_argument("--json", action="store_true", help="输出 JSON")
    p.set_defaults(func=cmd_models)

    p = sub.add_parser("verify", help="校验权重 sha256")
    p.add_argument("--registry", help="registry.json 路径")
    p.add_argument("--no-recompute", action="store_true", help="只检查文件是否存在")
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("activate", help="启用/回滚模型版本")
    p.add_argument("--model", required=True, help="模型 id/version")
    p.add_argument("--registry", help="registry.json 路径")
    p.set_defaults(func=cmd_activate)

    p = sub.add_parser("predict", help="单图推理")
    p.add_argument("--image", required=True, help="输入影像路径")
    p.add_argument("--model", default=None, help="模型 id/version；默认 active")
    p.add_argument("--registry", help="registry.json 路径")
    p.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    p.add_argument("--out-dir", help="输出目录")
    p.add_argument("--tta", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--postproc", action=argparse.BooleanOptionalAction, default=None)
    p.add_argument("--threshold", type=float, default=None)
    p.add_argument("--min-area", type=float, default=None)
    p.set_defaults(func=cmd_predict)

    p = sub.add_parser("evaluate", help="运行离线评估（耗时较长）")
    p.add_argument("--model", default=None, help="模型 id/version；默认 active")
    p.add_argument("--registry", help="registry.json 路径")
    p.add_argument("--out-tag", help="eval_postproc 输出标签")
    p.add_argument("--timeout", type=int, default=7200)
    p.add_argument("--device", choices=["auto", "cpu", "cuda"], default="auto")
    p.add_argument("--tolerance", type=float, default=1e-3)
    p.set_defaults(func=cmd_evaluate)

    p = sub.add_parser("verify-metrics", help="运行 verify_metrics.py")
    p.add_argument("--timeout", type=int, default=600)
    p.add_argument("--output", help="将回归结果写入 JSON 文件")
    p.set_defaults(func=cmd_verify_metrics)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.func(args))
    except AlgoError as exc:
        _print_json({"status": "failed", **exc.to_dict()})
        return 2
    except Exception as exc:  # CLI boundary: return a structured error
        _print_json({"status": "failed", "code": "INTERNAL_ERROR", "message": str(exc)})
        return 2


if __name__ == "__main__":
    sys.exit(main())
