"""Transactional outbox + database-backed task results. No torch import in API."""

import hashlib
import io
import json
import logging
import math
from datetime import timedelta
from functools import lru_cache

from celery import Celery
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select, update

from . import models as m
from .common import audit, get
from .config import settings
from .db import SessionLocal, now
from .storage import storage

logger = logging.getLogger(__name__)
app = Celery("bidlsp-platform", broker=settings.redis_url, backend=settings.redis_url)
app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    broker_connection_retry_on_startup=True,
    beat_schedule={
        "outbox": {"task": "platform.dispatch", "schedule": 5.0},
        "timeouts": {"task": "platform.timeouts", "schedule": 60.0},
    },
)


@lru_cache(maxsize=2)
def predictor(model_id, name, version, digest, config_json, weights_key):
    from algo.adapter.config import ModelConfig
    from algo.adapter.predictor import Predictor
    from algo.adapter.registry import ModelVersion

    target = settings.work_dir / "models" / (digest + ".pth")
    if not target.exists():
        storage.download("bidlsp-model", weights_key, target)
    with target.open("rb") as stream:
        actual = hashlib.file_digest(stream, "sha256").hexdigest()
    if actual != digest:
        target.unlink()
        raise ValueError("weight integrity check failed")
    record = ModelVersion(
        id=model_id,
        name=name,
        version=version,
        weights_path=target,
        weights_sha256=digest,
        config=ModelConfig.from_dict(json.loads(config_json)),
    )
    return Predictor(record, device=settings.device)


def get_predictor(db, version):
    model = get(db, m.Model, version.model_id)
    return predictor(
        version.id,
        model.name,
        version.version,
        version.weights_sha256,
        json.dumps(version.config, sort_keys=True),
        version.weights_key,
    )


def run_prediction(db, task):
    image = get(db, m.Image, task.image_id)
    model = get(db, m.ModelVersion, task.model_version_id)
    path = settings.work_dir / task.id / "image.png"
    storage.download("bidlsp-curated", image.preview_key, path)
    prediction = get_predictor(db, model).predict_path(path, **task.params)
    return prediction.save(settings.work_dir / task.id / "result", metadata={"task_id": task.id})


def execute_inference(task_id):
    with SessionLocal() as db:
        changed = db.execute(
            update(m.InferenceTask)
            .where(m.InferenceTask.id == task_id, m.InferenceTask.status == "queued")
            .values(status="running", started_at=now())
        ).rowcount
        db.commit()
        if not changed:
            return
        task = get(db, m.InferenceTask, task_id)
        try:
            cached = db.scalar(
                select(m.InferenceResult)
                .join(m.InferenceTask, m.InferenceResult.task_id == m.InferenceTask.id)
                .where(m.InferenceTask.cache_key == task.cache_key, m.InferenceTask.status == "succeeded")
                .order_by(m.InferenceTask.finished_at.desc())
            )
            if cached:
                values = {
                    k: getattr(cached, k)
                    for k in (
                        "mask_key",
                        "mask_rle",
                        "prob_mean",
                        "lesion_area_ratio",
                        "quality_flags",
                        "elapsed_ms",
                        "artifacts",
                    )
                }
            else:
                output = run_prediction(db, task)
                artifact_keys = {}
                for name, path in output["artifacts"].items():
                    if name == "result":
                        continue
                    key = f"results/{task.id}/{name}.png"
                    storage.put_file("bidlsp-result", key, path, "image/png")
                    artifact_keys[name] = key
                values = {
                    k: output["result"][k]
                    for k in ("mask_rle", "prob_mean", "lesion_area_ratio", "quality_flags", "elapsed_ms")
                }
                values.update(mask_key=artifact_keys["mask"], artifacts=artifact_keys)
                storage.put(
                    "bidlsp-result",
                    f"results/{task.id}/result.json",
                    json.dumps(
                        {"params": task.params, "model_version_id": task.model_version_id, **values}
                    ).encode(),
                    "application/json",
                )
            db.add(m.InferenceResult(task_id=task.id, **values))
            task.status, task.finished_at = "succeeded", now()
            image = get(db, m.Image, task.image_id)
            audit(
                db,
                None,
                "inference.finish",
                task,
                detail={"study_id": image.study_id, "cached": bool(cached)},
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            task = get(db, m.InferenceTask, task_id)
            task.status, task.finished_at = "failed", now()
            task.error = {
                "code": "INFERENCE_TIMEOUT" if isinstance(exc, SoftTimeLimitExceeded) else "INFERENCE_FAILED",
                "message": "推理未完成；请检查权重、影像与 Worker 日志",
            }
            audit(db, None, "inference.finish", task, detail={"status": "failed", "code": task.error["code"]})
            db.commit()
            logger.exception("Inference %s failed", task_id)


def finite_json(value):
    if isinstance(value, dict):
        return {k: finite_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [finite_json(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def run_evaluation(db, job):
    """Reuse B's predictor and the frozen evaluation functions on manifest masks.

    A3 searches validation probabilities only; the test partition never tunes a threshold.
    """
    import numpy as np
    from PIL import Image

    from algo.adapter.paths import ensure_transunet_importable

    ensure_transunet_importable()
    from eval_postproc import run_variant, search_threshold

    from algo.worker.eval_worker import summarize_eval_data

    version = get(db, m.ModelVersion, job.model_version_id)
    pred = get_predictor(db, version)
    items = list(
        db.scalars(
            select(m.DatasetItem)
            .where(m.DatasetItem.dataset_version_id == job.dataset_version_id)
            .order_by(m.DatasetItem.image_id)
        )
    )

    def collect(split):
        probs, masks, classes, names = [], [], [], []
        for item in items:
            if item.split != split:
                continue
            image = get(db, m.Image, item.image_id)
            path = settings.work_dir / job.id / (image.id + ".png")
            storage.download("bidlsp-curated", image.preview_key, path)
            prediction = pred.predict_path(path, tta=version.config["tta"], postproc=True)
            probs.append(prediction.prob)
            with Image.open(io.BytesIO(storage.read("bidlsp-curated", item.mask_ref))) as mask:
                masks.append(np.asarray(mask.convert("L")) > 0)
            classes.append(image.class_label)
            names.append(image.relative_path)
        if not probs or not any(c != "normal" for c in classes):
            raise ValueError("evaluation needs lesion samples in val and test")
        return probs, masks, classes, names

    vp, vg, vc, _ = collect("val")
    threshold, _ = search_threshold(
        vp, vg, vc, True, version.config["min_area"], np.round(np.arange(0.05, 1, 0.05), 4)
    )
    tp, tg, tc, tn = collect("test")
    raw = {"variants": {}}
    for name, t in (("A2+A1", 0.5), ("A2+A1+A3", threshold)):
        agg, per = run_variant(tp, tg, tc, tn, t, True, version.config["min_area"])
        raw["variants"][name] = {"threshold": float(t), "postproc": True, "agg": agg, "per_image": per}
    metrics = finite_json(summarize_eval_data(raw))
    for values in metrics.values():
        agg = values["agg"]
        values.update(
            {
                "dice": agg.get("dice_lesion"),
                "iou": agg.get("iou_lesion"),
                **{
                    key: agg.get(key)
                    for key in ("precision", "recall", "specificity", "hd95", "asd", "fg_ratio_normal")
                },
            }
        )
    raw = finite_json(raw)
    expected = version.metrics or {}
    comparisons = {
        name: {"expected": expected.get(name, {}).get("dice"), "actual": values.get("dice")}
        for name, values in metrics.items()
    }
    # A different dataset has no baseline equivalence claim, even if a number happens to match.
    from .config import ROOT

    reference = json.loads((ROOT / "transunet/data/splits/busi_seed0.json").read_text())
    equivalent = all(
        sorted(get(db, m.Image, i.image_id).relative_path for i in items if i.split == split)
        == sorted(reference[split])
        for split in ("val", "test")
    )
    equivalent = equivalent and all(get(db, m.Annotation, i.annotation_id).source == "import" for i in items)
    equivalent = equivalent and version.config["tta"] and version.config["min_area"] == 0.001
    passed = (
        equivalent
        and bool(comparisons)
        and all(
            v["expected"] is not None
            and v["actual"] is not None
            and abs(v["actual"] - v["expected"]) <= 0.001
            for v in comparisons.values()
        )
    )
    regression = {
        "expected": expected,
        "result": "PASS" if passed else "FAIL",
        "comparable_split": equivalent,
        "comparison": comparisons,
        "definition": "固定 val/test + 导入参考掩膜；A3 仅在 val 搜索阈值，Dice 容差 1e-3",
    }
    return metrics, regression, raw


def execute_evaluation(job_id):
    with SessionLocal() as db:
        changed = db.execute(
            update(m.EvaluationJob)
            .where(m.EvaluationJob.id == job_id, m.EvaluationJob.status == "queued")
            .values(status="running", started_at=now())
        ).rowcount
        db.commit()
        if not changed:
            return
        job = get(db, m.EvaluationJob, job_id)
        try:
            metrics, regression, raw = run_evaluation(db, job)
            job.metrics, job.regression = metrics, regression
            job.result_key = storage.put(
                "bidlsp-result", f"evaluations/{job.id}.json", json.dumps(raw).encode(), "application/json"
            )
            job.status = "succeeded"
        except Exception:
            db.rollback()
            job = get(db, m.EvaluationJob, job_id)
            job.status, job.error = (
                "failed",
                {"code": "EVALUATION_FAILED", "message": "评估失败，请检查数据、权重与 Worker 日志"},
            )
            logger.exception("Evaluation %s failed", job_id)
        job.finished_at = now()
        audit(db, None, "evaluation.finish", job, detail={"status": job.status})
        db.commit()


@app.task(name="platform.import", soft_time_limit=3500, time_limit=3600)
def import_task(id):
    from .data_service import import_archive

    import_archive(id)


@app.task(name="platform.inference", soft_time_limit=240, time_limit=300)
def inference_task(id):
    execute_inference(id)


@app.task(name="platform.evaluation", soft_time_limit=7100, time_limit=7200)
def evaluation_task(id):
    execute_evaluation(id)


@app.task(name="platform.dispatch")
def dispatch():
    with SessionLocal() as db:
        entries = list(
            db.scalars(
                select(m.Outbox)
                .where(m.Outbox.published_at.is_(None))
                .order_by(m.Outbox.created_at)
                .limit(100)
                .with_for_update(skip_locked=True)
            )
        )
        for entry in entries:
            queue = {"import": "default", "inference": "inference.cpu", "evaluation": "eval"}[entry.kind]
            app.send_task("platform." + entry.kind, args=[entry.object_id], queue=queue, task_id=entry.id)
            entry.published_at = now()
        db.commit()


@app.task(name="platform.timeouts")
def timeouts():
    with SessionLocal() as db:
        for job in db.scalars(
            select(m.ImportJob).where(
                m.ImportJob.status.in_(["validating", "importing"]),
                m.ImportJob.started_at < now() - timedelta(seconds=3700),
            )
        ):
            job.status, job.finished_at = "failed", now()
            job.report = {"error": "导入 Worker 超时或退出，请重新提交；已入湖图像将被去重"}
            audit(db, None, "data.import.timeout", job)
        for cls, limit in ((m.InferenceTask, 360), (m.EvaluationJob, 7300)):
            rows = db.scalars(
                select(cls).where(cls.status == "running", cls.started_at < now() - timedelta(seconds=limit))
            )
            for obj in rows:
                obj.status, obj.finished_at = "failed", now()
                obj.error = {
                    "code": "INFERENCE_TIMEOUT" if cls is m.InferenceTask else "EVALUATION_FAILED",
                    "message": "Worker 超时或退出，请重新提交",
                }
                audit(db, None, "task.timeout", obj)
        db.commit()


def drain_eager():
    """Explicit test/development mode; never enabled in Compose."""
    with SessionLocal() as db:
        entries = list(db.scalars(select(m.Outbox).where(m.Outbox.published_at.is_(None))))
        for entry in entries:
            {"import": import_task, "inference": inference_task, "evaluation": evaluation_task}[
                entry.kind
            ].run(entry.object_id)
            entry.published_at = now()
        db.commit()
