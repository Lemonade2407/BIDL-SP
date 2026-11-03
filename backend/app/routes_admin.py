from collections import Counter
from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select

from . import models as m
from .common import APIError, page, reply, serialize, user_ref
from .db import get_db
from .security import require

router = APIRouter()


def screening_stats(db, params):
    stmt = select(m.ScreenTask)
    for field, lower in (("from", True), ("to", False)):
        if params.get(field):
            try:
                timestamp = datetime.fromisoformat(params[field].replace("Z", "+00:00"))
                if timestamp.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise APIError(422, "日期必须为带时区 ISO 8601") from None
            stmt = stmt.where(
                m.ScreenTask.created_at >= timestamp if lower else m.ScreenTask.created_at <= timestamp
            )
    tasks = list(db.scalars(stmt))
    study_ids = [t.study_id for t in tasks]
    reviews = list(
        db.scalars(
            select(m.StudyReview)
            .where(m.StudyReview.study_id.in_(study_ids))
            .order_by(m.StudyReview.created_at)
        )
    )
    latest = {r.study_id: r for r in reviews}
    positive = negative = 0
    for review in latest.values():
        if review.decision == "reject":
            continue
        if review.annotation_id:
            annotation = db.get(m.Annotation, review.annotation_id)
            foreground = sum(annotation.mask_rle["counts"][1::2]) > 0
        elif review.inference_result_id:
            foreground = db.get(m.InferenceResult, review.inference_result_id).lesion_area_ratio > 0
        else:
            continue
        positive += foreground
        negative += not foreground
    durations = [
        (t.finished_at - t.claimed_at).total_seconds() for t in tasks if t.finished_at and t.claimed_at
    ]
    return {
        "by_status": dict(Counter(t.status for t in tasks)),
        "by_decision": dict(Counter(r.decision for r in latest.values())),
        "positive": positive,
        "negative": negative,
        "pending_review": sum(t.status != "done" for t in tasks),
        "positive_rate": positive / (positive + negative) if positive + negative else 0,
        "avg_review_seconds": sum(durations) / len(durations) if durations else 0,
        "definition": "按任务创建时间过滤；每检查最新复核接受/修改且最终掩膜非空计为参考阳性；非诊断结论。复核时长=完成时间-领取时间。",
    }


@router.get("/stats/overview")
def overview(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("stats:read"))):
    data = {}
    for name, cls, condition in (
        ("images", m.Image, None),
        ("annotations_approved", m.Annotation, m.Annotation.status == "approved"),
        ("dataset_versions", m.DatasetVersion, None),
        ("model_versions", m.ModelVersion, None),
        ("screen_tasks", m.ScreenTask, None),
        ("reports_signed", m.Report, m.Report.status == "signed"),
    ):
        stmt = select(func.count()).select_from(cls)
        if condition is not None:
            stmt = stmt.where(condition)
        data[name] = db.scalar(stmt)
    stats = screening_stats(db, {})
    data.update({k: stats[k] for k in ("positive_rate", "avg_review_seconds", "definition")})
    return reply(request, data)


@router.get("/stats/annotations")
def annotations(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("stats:read"))):
    stmt = select(m.Image)
    if request.query_params.get("dataset_version_id"):
        stmt = stmt.where(
            m.Image.id.in_(
                select(m.DatasetItem.image_id).where(
                    m.DatasetItem.dataset_version_id == request.query_params["dataset_version_id"]
                )
            )
        )
    images = list(db.scalars(stmt))
    latest = {
        a.image_id: a
        for a in db.scalars(
            select(m.Annotation)
            .where(m.Annotation.image_id.in_([i.id for i in images]))
            .order_by(m.Annotation.version)
        )
    }
    by_status = dict(Counter(latest[i.id].status if i.id in latest else "none" for i in images))
    return reply(
        request,
        {
            "by_class": dict(Counter(i.class_label for i in images)),
            "by_status": by_status,
            "completion_rate": by_status.get("approved", 0) / len(images) if images else 0,
            "definition": "每张影像仅计最新标注；完成率=最新标注 approved 的影像数/所选影像数",
        },
    )


@router.get("/stats/models")
def models(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("stats:read"))):
    stmt = select(m.ModelVersion)
    if request.query_params.get("model_id"):
        stmt = stmt.where(m.ModelVersion.model_id == request.query_params["model_id"])
    versions = list(db.scalars(stmt))
    return reply(
        request,
        {
            "versions": [
                {
                    "id": v.id,
                    "version": v.version,
                    "seeds": [v.config["seed"]],
                    **(v.metrics or {}).get("A2+A1", {}),
                    "variants": v.metrics,
                }
                for v in versions
            ],
            "definition": "模型注册时登记的指标；实际冻结数据集评估见 evaluations，不能将登记值作为实测值",
        },
    )


@router.get("/stats/screening")
def screening(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("stats:read"))):
    return reply(request, screening_stats(db, request.query_params))


@router.get("/audit-logs")
def audit_logs(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("audit:read"))):
    stmt = select(m.AuditLog)
    for field in ("actor_id", "action", "object_type", "object_id"):
        if request.query_params.get(field):
            stmt = stmt.where(getattr(m.AuditLog, field) == request.query_params[field])
    for field, lower in (("from", True), ("to", False)):
        if request.query_params.get(field):
            try:
                stamp = datetime.fromisoformat(request.query_params[field].replace("Z", "+00:00"))
                if stamp.tzinfo is None:
                    raise ValueError()
            except ValueError:
                raise APIError(422, "时间必须带时区") from None
            stmt = stmt.where(m.AuditLog.created_at >= stamp if lower else m.AuditLog.created_at <= stamp)
    return page(request, db, stmt, m.AuditLog, lambda x: {**serialize(x), "actor": user_ref(db, x.actor_id)})
