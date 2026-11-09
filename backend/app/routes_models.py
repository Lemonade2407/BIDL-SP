from fastapi import APIRouter, Depends, Request
from sqlalchemy import select, update

from . import models as m
from . import schemas as s
from .common import APIError, audit, fingerprint, get, page, queue, remember, replay, reply, serialize
from .config import settings
from .db import get_db, now
from .routes_annotations import save_annotation
from .security import current_user, require
from .storage import storage

router = APIRouter()


def result_json(obj):
    if obj is None:
        return None
    data = serialize(obj)
    data["mask_url"] = storage.url("bidlsp-result", obj.mask_key)
    data["artifacts"] = {k: storage.url("bidlsp-result", v) for k, v in obj.artifacts.items()}
    return data


def inference_json(db, obj):
    return {
        **serialize(obj),
        "result": result_json(
            db.scalar(select(m.InferenceResult).where(m.InferenceResult.task_id == obj.id))
        ),
    }


def resolve_model(db, id=None):
    if id:
        return get(db, m.ModelVersion, id)
    obj = db.scalar(select(m.ModelVersion).where(m.ModelVersion.status == "active"))
    if obj is None:
        raise APIError(503, "没有启用模型", "MODEL_UNAVAILABLE")
    return obj


def new_inference(db, image_id, model, params, user, request, batch_id=None, attempt=1):
    image = get(db, m.Image, image_id)
    merged = {k: model.config[k] for k in ("tta", "threshold", "postproc", "min_area")}
    merged.update(params.model_dump(exclude_none=True))
    key = fingerprint(
        {"image": image.sha256, "weights": model.weights_sha256, "config": model.config, "params": merged}
    )
    obj = m.InferenceTask(
        image_id=image_id,
        model_version_id=model.id,
        params=merged,
        requested_by=user.id,
        batch_id=batch_id,
        attempt=attempt,
        cache_key=key,
    )
    db.add(obj)
    queue(db, "inference", obj)
    audit(db, user, "inference.create", obj, request, {"study_id": image.study_id})
    return obj


@router.get("/models")
def models(request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    stmt = select(m.Model)
    if request.query_params.get("task"):
        stmt = stmt.where(m.Model.task == request.query_params["task"])

    def model_json(model):
        versions = list(
            db.scalars(
                select(m.ModelVersion)
                .where(m.ModelVersion.model_id == model.id)
                .order_by(m.ModelVersion.created_at)
            )
        )
        active = next((item for item in versions if item.status == "active"), None)
        return {
            **serialize(model),
            "active_version": serialize(active),
            "versions": [serialize(item) for item in versions],
        }

    return page(request, db, stmt, m.Model, model_json)


@router.post("/models", status_code=201)
def create_model(
    body: s.ModelCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("model:manage")),
):
    obj = m.Model(**body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "model.create", obj, request)
    return reply(request, serialize(obj), 201)


@router.post("/models/{id}/versions", status_code=201)
def create_version(
    id: str,
    body: s.ModelVersionCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("model:manage")),
):
    get(db, m.Model, id)
    try:
        digest = storage.sha256("bidlsp-model", body.weights_key)
    except (OSError, FileNotFoundError):
        raise APIError(422, "权重对象不存在") from None
    if digest != body.weights_sha256:
        raise APIError(422, "权重 sha256 不匹配")
    obj = m.ModelVersion(model_id=id, created_by=user.id, **body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "model.version.create", obj, request)
    return reply(request, serialize(obj), 201)


@router.get("/model-versions/{id}")
def version(id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    return reply(request, serialize(get(db, m.ModelVersion, id)))


def verification_blocker(version):
    """Return why a version is not verifiable, or None when it may be activated."""
    if not version.metrics:
        return "缺少指标：请先完成平台离线评估或登记指标"
    if (version.regression or {}).get("result") == "FAIL":
        return "该版本的平台评估回归未通过（FAIL）"
    if version.metrics_source != "platform_eval":
        return "该版本尚未在平台完成离线评估，指标仅来自注册登记"
    return None


@router.post("/model-versions/{id}/activate")
def activate(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("model:manage"))
):
    obj = get(db, m.ModelVersion, id)
    get(db, m.Model, obj.model_id, lock=True)
    blocker = verification_blocker(obj)
    failed_regression = (obj.regression or {}).get("result") == "FAIL"
    override = bool(blocker) and not failed_regression and settings.allow_unverified_model
    if blocker and not override:
        hint = "" if failed_regression else "；如为演示确需启用，请设置 ALLOW_UNVERIFIED_MODEL=true"
        raise APIError(409, blocker + hint, "MODEL_NOT_VERIFIED")
    previous = db.scalar(
        select(m.ModelVersion).where(
            m.ModelVersion.model_id == obj.model_id, m.ModelVersion.status == "active"
        )
    )
    db.execute(
        update(m.ModelVersion)
        .where(m.ModelVersion.model_id == obj.model_id, m.ModelVersion.status == "active")
        .values(status="archived")
    )
    db.flush()
    obj.status, obj.activated_at = "active", now()
    audit(
        db,
        user,
        "model.activate",
        obj,
        request,
        {
            "from_version": previous.id if previous and previous.id != obj.id else None,
            "override": override,
            "blocker": blocker,
        },
    )
    db.flush()
    result = serialize(obj)
    if override:
        result["warning"] = blocker
    return reply(request, result)


@router.post("/inference-tasks", status_code=202)
def inference(
    body: s.InferenceCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("inference:create")),
):
    payload = body.model_dump()
    previous = replay(request, db, user, payload)
    if previous:
        return previous
    obj = new_inference(
        db, body.image_id, resolve_model(db, body.model_version_id), body.params, user, request
    )
    result = {"task_id": obj.id, "status": obj.status, "created_at": obj.created_at}
    remember(request, db, user, payload, result)
    return reply(request, result, 202)


@router.get("/inference-tasks/{id}")
def inference_detail(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)
):
    return reply(request, inference_json(db, get(db, m.InferenceTask, id)))


@router.post("/inference-batches", status_code=202)
def batch(
    body: s.BatchCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("inference:create")),
):
    payload = body.model_dump()
    previous = replay(request, db, user, payload)
    if previous:
        return previous
    version = get(db, m.DatasetVersion, body.dataset_version_id)
    if version.status != "frozen":
        raise APIError(409, "数据集版本尚未冻结")
    model = resolve_model(db, body.model_version_id)
    obj = m.InferenceBatch(**payload, created_by=user.id)
    db.add(obj)
    db.flush()
    items = list(db.scalars(select(m.DatasetItem).where(m.DatasetItem.dataset_version_id == version.id)))
    for item in items:
        new_inference(db, item.image_id, model, body.params, user, request, obj.id)
    result = {"batch_id": obj.id, "status": "queued", "total": len(items)}
    remember(request, db, user, payload, result)
    audit(db, user, "inference.batch.create", obj, request)
    return reply(request, result, 202)


def latest_attempts(db, batch_id):
    """One task per image: retries create attempt+1 instead of overwriting history."""
    latest = {}
    for task in db.scalars(select(m.InferenceTask).where(m.InferenceTask.batch_id == batch_id)):
        if task.image_id not in latest or task.attempt > latest[task.image_id].attempt:
            latest[task.image_id] = task
    return latest


@router.get("/inference-batches/{id}")
def batch_detail(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("inference:create"))
):
    obj = get(db, m.InferenceBatch, id)
    states = [task.status for task in latest_attempts(db, id).values()]
    total, done, failed = len(states), states.count("succeeded"), states.count("failed")
    status = "queued" if all(s == "queued" for s in states) else "running"
    if done + failed == total:
        status = "succeeded" if not failed else "failed" if not done else "partial"
    return reply(
        request,
        {
            **serialize(obj),
            "status": status,
            "total": total,
            "succeeded": done,
            "failed": failed,
            "progress": (done + failed) / total if total else 1,
        },
    )


@router.post("/inference-batches/{id}/retry")
def batch_retry(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("inference:create"))
):
    batch = get(db, m.InferenceBatch, id, lock=True)
    model = get(db, m.ModelVersion, batch.model_version_id)
    params = s.InferenceParams(**batch.params)
    retried, in_flight = [], 0
    for image_id, task in latest_attempts(db, batch.id).items():
        if task.status == "failed":
            new_inference(
                db,
                image_id,
                model,
                params,
                user,
                request,
                batch_id=batch.id,
                attempt=task.attempt + 1,
            )
            retried.append(image_id)
        elif task.status in ("queued", "running"):
            in_flight += 1
    audit(
        db,
        user,
        "inference.batch.retry",
        batch,
        request,
        {"retried": len(retried), "in_flight": in_flight},
    )
    db.flush()
    return reply(request, {"batch_id": batch.id, "retried": len(retried), "in_flight": in_flight})


@router.post("/inference-batches/{id}/to-annotations", status_code=201)
def batch_to_annotations(
    id: str,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("annotation:manage")),
):
    batch = get(db, m.InferenceBatch, id)
    created, skipped, task_ids = 0, 0, []
    tasks = list(
        db.scalars(
            select(m.InferenceTask).where(
                m.InferenceTask.batch_id == batch.id, m.InferenceTask.status == "succeeded"
            )
        )
    )
    for task in tasks:
        result = db.scalar(select(m.InferenceResult).where(m.InferenceResult.task_id == task.id))
        if result is None:
            skipped += 1
            continue
        image = get(db, m.Image, task.image_id)
        if db.scalar(
            select(m.Annotation.id).where(
                m.Annotation.image_id == image.id, m.Annotation.status.in_(["pending", "approved"])
            )
        ):
            skipped += 1
            continue
        open_task = db.scalar(
            select(m.AnnotationTask)
            .where(m.AnnotationTask.image_id == image.id, m.AnnotationTask.status != "approved")
            .with_for_update()
        )
        if open_task and open_task.annotation_id:
            skipped += 1
            continue
        annotation = save_annotation(
            db,
            s.AnnotationCreate(
                image_id=image.id,
                mask_rle=result.mask_rle,
                is_empty=sum(result.mask_rle["counts"][1::2]) == 0,
                source="model",
                note="批量推理预标注；请标注员核对修边",
            ),
            user,
            enforce_owner=False,
            link_task=False,
        )
        if open_task:
            open_task.annotation_id = annotation.id
        else:
            open_task = m.AnnotationTask(
                image_id=image.id,
                dataset_version_id=batch.dataset_version_id,
                annotation_id=annotation.id,
            )
            db.add(open_task)
            db.flush()
            task_ids.append(open_task.id)
        audit(
            db,
            user,
            "annotation.preannot.batch",
            annotation,
            request,
            {"batch_id": batch.id, "task_id": open_task.id},
        )
        created += 1
    return reply(request, {"created": created, "skipped": skipped, "task_ids": task_ids}, 201)


@router.post("/evaluations", status_code=202)
def evaluation(
    body: s.EvaluationCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("model:manage")),
):
    model = get(db, m.ModelVersion, body.model_version_id)
    if not model.config["tta"]:
        raise APIError(422, "A2+A1/A2+A1+A3 评估协议要求模型 tta=true")
    version = get(db, m.DatasetVersion, body.dataset_version_id)
    if version.status != "frozen":
        raise APIError(409, "只能评估冻结版本")
    obj = m.EvaluationJob(**body.model_dump(), created_by=user.id)
    db.add(obj)
    queue(db, "evaluation", obj)
    audit(db, user, "evaluation.create", obj, request)
    return reply(request, {"evaluation_id": obj.id, "status": obj.status}, 202)


@router.get("/evaluations")
def evaluations(
    request: Request, db=Depends(get_db, scope="function"), user=Depends(require("model:manage"))
):
    stmt = select(m.EvaluationJob)
    for field in ("model_version_id", "dataset_version_id", "status"):
        if request.query_params.get(field):
            stmt = stmt.where(getattr(m.EvaluationJob, field) == request.query_params[field])
    return page(request, db, stmt, m.EvaluationJob)


@router.get("/evaluations/{id}")
def evaluation_detail(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("model:manage"))
):
    return reply(request, serialize(get(db, m.EvaluationJob, id)))


@router.get("/metrics/regression")
def regression(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("model:manage"))):
    stmt = select(m.EvaluationJob).where(m.EvaluationJob.status == "succeeded")
    if request.query_params.get("model_id"):
        stmt = stmt.where(
            m.EvaluationJob.model_version_id.in_(
                select(m.ModelVersion.id).where(m.ModelVersion.model_id == request.query_params["model_id"])
            )
        )
    job = db.scalar(stmt.order_by(m.EvaluationJob.finished_at.desc()))
    if not job:
        raise APIError(404, "尚无完成的在线评估；登记指标不等同于实测回归")
    return reply(request, {**job.regression, "actual": job.metrics, "checked_at": job.finished_at})
