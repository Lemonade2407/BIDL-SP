from fastapi import APIRouter, Depends, Request
from PIL import Image as PILImage
from sqlalchemy import func, select, update

from algo.adapter.rle import rle_decode

from . import models as m
from . import schemas as s
from .common import APIError, audit, get, page, reply, serialize, user_ref
from .data_service import png
from .db import get_db, now, uid
from .security import current_user, require
from .storage import storage

router = APIRouter()


def annotation_json(db, obj):
    result = serialize(obj)
    result.update(annotator=user_ref(db, obj.annotator_id), reviewed_by=user_ref(db, obj.reviewed_by_id))
    return result


def save_annotation(db, body, user, *, enforce_owner=True):
    image = get(db, m.Image, body.image_id, lock=True)
    if body.mask_rle.size != [image.height, image.width]:
        raise APIError(422, "掩膜必须使用原始影像尺寸")
    mask = rle_decode(body.mask_rle.model_dump())
    if not mask.any() and not body.is_empty:
        raise APIError(422, "空掩膜必须显式设置 is_empty=true")
    if mask.any() and body.is_empty:
        raise APIError(422, "非空掩膜不能设置 is_empty=true")
    task = db.scalar(
        select(m.AnnotationTask)
        .where(m.AnnotationTask.image_id == image.id, m.AnnotationTask.status != "approved")
        .with_for_update()
    )
    if enforce_owner and (not task or task.assignee_id != user.id):
        raise APIError(409, "请先领取本人标注任务")
    if task and task.status == "submitted":
        raise APIError(409, "待审核标注不能继续编辑")
    if db.scalar(
        select(m.Annotation.id).where(m.Annotation.image_id == image.id, m.Annotation.status == "pending")
    ):
        raise APIError(409, "该影像已有待审核版本")
    version = (
        db.scalar(select(func.max(m.Annotation.version)).where(m.Annotation.image_id == image.id)) or 0
    ) + 1
    id = uid()
    key = storage.put(
        "bidlsp-curated",
        f"annotations/{image.id}/{id}.png",
        png(PILImage.fromarray(mask.astype("uint8") * 255)),
        "image/png",
    )
    obj = m.Annotation(
        id=id,
        **body.model_dump(exclude={"mask_rle"}),
        mask_rle=body.mask_rle.model_dump(),
        mask_key=key,
        version=version,
        annotator_id=user.id,
    )
    db.add(obj)
    db.flush()
    if task:
        task.annotation_id, task.status = obj.id, "in_progress"
    return obj


def claim(db, cls, id, user):
    get(db, cls, id)
    result = db.execute(
        update(cls)
        .where(cls.id == id, cls.status == "pending", cls.assignee_id.is_(None))
        .values(status="in_progress", assignee_id=user.id, claimed_at=now())
    )
    if result.rowcount != 1:
        raise APIError(409, "任务已被领取或已完成")
    db.flush()
    return get(db, cls, id)


@router.post("/annotation-tasks", status_code=201)
def create_tasks(
    body: s.AnnotationTaskCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("annotation:manage")),
):
    stmt = select(m.Image)
    if body.dataset_version_id:
        version = get(db, m.DatasetVersion, body.dataset_version_id)
        if version.status != "frozen":
            raise APIError(409, "版本尚未冻结")
        stmt = stmt.where(
            m.Image.id.in_(
                select(m.DatasetItem.image_id).where(m.DatasetItem.dataset_version_id == version.id)
            )
        )
    else:
        stmt = stmt.where(m.Image.id.in_(body.image_ids))
        if len(list(db.scalars(stmt))) != len(set(body.image_ids)):
            raise APIError(404, "部分影像不存在")
    if body.class_labels:
        stmt = stmt.where(m.Image.class_label.in_(body.class_labels))
    existing = select(m.AnnotationTask.image_id).where(m.AnnotationTask.status != "approved")
    images = list(db.scalars(stmt.where(m.Image.id.not_in(existing)).order_by(m.Image.id).limit(body.count)))
    tasks = []
    for image in images:
        obj = m.AnnotationTask(
            image_id=image.id, dataset_version_id=body.dataset_version_id, priority=body.priority
        )
        db.add(obj)
        db.flush()
        tasks.append(obj.id)
        audit(db, user, "annotation.task.create", obj, request)
    return reply(request, {"created": len(tasks), "task_ids": tasks}, 201)


@router.get("/annotation-tasks")
def tasks(
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("annotation:edit", "annotation:manage", "annotation:review")),
):
    stmt = select(m.AnnotationTask)
    for field in ("status", "dataset_version_id"):
        if request.query_params.get(field):
            stmt = stmt.where(getattr(m.AnnotationTask, field) == request.query_params[field])
    if request.query_params.get("assignee") == "me":
        stmt = stmt.where(m.AnnotationTask.assignee_id == user.id)
    return page(
        request,
        db,
        stmt,
        m.AnnotationTask,
        lambda x: {**serialize(x), "assignee": user_ref(db, x.assignee_id)},
    )


@router.post("/annotation-tasks/{id}/claim")
def claim_task(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("annotation:edit"))
):
    obj = claim(db, m.AnnotationTask, id, user)
    audit(db, user, "annotation.claim", obj, request)
    return reply(request, serialize(obj))


@router.get("/annotations/{id}")
def detail(
    id: str,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("annotation:edit", "annotation:review")),
):
    return reply(request, annotation_json(db, get(db, m.Annotation, id)))


@router.post("/annotations", status_code=201)
def save(
    body: s.AnnotationCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("annotation:edit")),
):
    if body.source not in ("manual", "preannot"):
        raise APIError(422, "model/import 来源仅由系统生成")
    obj = save_annotation(db, body, user)
    audit(db, user, "annotation.save", obj, request)
    return reply(request, annotation_json(db, obj), 201)


@router.post("/annotations/{id}/submit")
def submit(
    id: str,
    request: Request,
    body: s.Submit | None = None,
    db=Depends(get_db, scope="function"),
    user=Depends(require("annotation:edit")),
):
    obj = get(db, m.Annotation, id, lock=True)
    if obj.annotator_id != user.id:
        raise APIError(403, "只能提交本人标注")
    task = db.scalar(select(m.AnnotationTask).where(m.AnnotationTask.annotation_id == id).with_for_update())
    if obj.status != "draft" or not task or task.annotation_id != id or task.assignee_id != user.id:
        raise APIError(409, "只能提交当前任务的最新草稿")
    obj.status, task.status = "pending", "submitted"
    if body and body.note is not None:
        obj.note = body.note
    audit(db, user, "annotation.submit", obj, request)
    db.flush()
    return reply(request, annotation_json(db, obj))


@router.post("/annotations/{id}/reviews")
def review(
    id: str,
    body: s.AnnotationDecision,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("annotation:review")),
):
    obj = get(db, m.Annotation, id, lock=True)
    get(db, m.Image, obj.image_id, lock=True)
    if obj.annotator_id == user.id:
        raise APIError(403, "审核人不能是标注人")
    if obj.status != "pending":
        raise APIError(409, "标注不在待审核状态")
    if body.decision == "reject" and not (body.comment or "").strip():
        raise APIError(422, "驳回必须填写意见")
    if body.decision == "approve":
        db.execute(
            update(m.Annotation)
            .where(m.Annotation.image_id == obj.image_id, m.Annotation.status == "approved")
            .values(status="rejected")
        )
        db.flush()
    obj.status = "approved" if body.decision == "approve" else "draft"
    obj.reviewed_by_id, obj.review_comment, obj.reviewed_at = user.id, body.comment, now()
    db.add(m.AnnotationReview(annotation_id=id, reviewer_id=user.id, **body.model_dump()))
    task = db.scalar(select(m.AnnotationTask).where(m.AnnotationTask.annotation_id == id))
    if task:
        task.status = "approved" if body.decision == "approve" else "in_progress"
        task.finished_at = now() if body.decision == "approve" else None
    audit(db, user, "annotation.review", obj, request, body.model_dump())
    db.flush()
    return reply(request, annotation_json(db, obj))


@router.get("/images/{id}/annotations")
def history(id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    get(db, m.Image, id)
    return page(
        request,
        db,
        select(m.Annotation).where(m.Annotation.image_id == id),
        m.Annotation,
        lambda x: annotation_json(db, x),
    )
