"""Celery task entrypoints for the algorithm service.

The execution functions are independent of Celery so they can be unit-tested
and called directly. In production the backend enqueues a JSON payload:

    {"task_id": "...", "image_path": "/data/x.png",
     "model_version": "s256rgb-seed0", "params": {...}, "output_dir": "..."}

The backend is responsible for downloading an object from MinIO to a local
path before enqueueing; the worker writes artifacts locally and returns their
paths. The API layer maps those to signed URLs.
"""

from __future__ import annotations

import logging
import os
import uuid
from pathlib import Path
from typing import Any

from ..adapter.errors import AlgoError, ImageDecodeError
from ..adapter.paths import OUTPUT_DIR
from ..adapter.predictor import get_predictor
from ..adapter.registry import ModelRegistry
from .eval_worker import run_evaluation

logger = logging.getLogger(__name__)

_PARAM_KEYS = ("tta", "threshold", "postproc", "min_area")


def _inference_params(raw: dict[str, Any] | None) -> dict[str, Any]:
    return {k: raw[k] for k in _PARAM_KEYS if raw and k in raw}


def execute_inference(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one inference task and return an API-shaped result (never raises)."""
    task_id = str(payload.get("task_id") or uuid.uuid4())
    try:
        image_path = payload.get("image_path")
        if not image_path:
            raise ValueError("image_path is required")
        image_path = Path(image_path)
        if not image_path.exists():
            raise ImageDecodeError(f"image not found: {image_path}")

        model_key = (
            payload.get("model_version")
            or payload.get("model_id")
            or payload.get("model")
        )
        registry = ModelRegistry()
        predictor = get_predictor(
            model_key,
            device=str(payload.get("device", "auto")),
            registry=registry,
        )
        prediction = predictor.predict_path(
            image_path, **_inference_params(payload.get("params"))
        )

        output_dir = Path(payload.get("output_dir") or (OUTPUT_DIR / task_id))
        return prediction.save(
            output_dir, metadata={"task_id": task_id, "status": "succeeded"}
        )
    except AlgoError as exc:
        logger.warning("inference task %s failed: %s", task_id, exc)
        return {
            "task_id": task_id,
            "status": "failed",
            "error": {"code": exc.code, "message": exc.message},
        }
    except Exception as exc:  # worker must return structured failures
        logger.exception("inference task %s failed", task_id)
        return {
            "task_id": task_id,
            "status": "failed",
            "error": {"code": "INFERENCE_FAILED", "message": str(exc)},
        }


def execute_evaluation(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one offline evaluation task and return metrics / regression status."""
    evaluation_id = str(payload.get("evaluation_id") or uuid.uuid4())
    try:
        report = run_evaluation(
            payload.get("model_version") or payload.get("model_id"),
            out_tag=payload.get("out_tag"),
            timeout=int(payload.get("timeout", 7200)),
            device=str(payload.get("device", "auto")),
            tolerance=float(payload.get("tolerance", 1e-3)),
        )
        return {
            "evaluation_id": evaluation_id,
            "status": "succeeded",
            **report.to_dict(),
        }
    except AlgoError as exc:
        logger.warning("evaluation task %s failed: %s", evaluation_id, exc)
        return {
            "evaluation_id": evaluation_id,
            "status": "failed",
            "error": {"code": exc.code, "message": exc.message},
        }
    except Exception as exc:
        logger.exception("evaluation task %s failed", evaluation_id)
        return {
            "evaluation_id": evaluation_id,
            "status": "failed",
            "error": {"code": "EVALUATION_FAILED", "message": str(exc)},
        }


try:  # Celery is optional for CLI / unit tests
    from celery import Celery
except ImportError:  # pragma: no cover - exercised only without celery installed
    Celery = None  # type: ignore[assignment]

if Celery is not None:
    _redis = os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    app = Celery("bidlsp", broker=_redis, backend=_redis)
    app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_default_queue="inference.cpu",
        worker_prefetch_multiplier=1,
        task_routes={
            "algo.worker.tasks.inference_task": {"queue": "inference.cpu"},
            "algo.worker.tasks.evaluation_task": {"queue": "eval"},
        },
    )

    @app.task(
        name="algo.worker.tasks.inference_task",
        bind=True,
        time_limit=300,
        soft_time_limit=240,
    )
    def inference_task(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        return execute_inference(payload)

    @app.task(
        name="algo.worker.tasks.evaluation_task",
        bind=True,
        time_limit=7200,
        soft_time_limit=7100,
    )
    def evaluation_task(self: Any, payload: dict[str, Any]) -> dict[str, Any]:
        return execute_evaluation(payload)
