from fastapi import APIRouter, Depends, Request
from PIL import Image as PILImage
from sqlalchemy import func, or_, select, update

from algo.adapter.rle import rle_decode

from . import models as m
from . import schemas as s
from .common import APIError, audit, get, page, reply, serialize, user_ref
from .data_service import png
from .db import get_db, now, uid
from .security import current_user, require
from .storage import storage

router = APIRouter()

# Two independent annotations with IoU at or above this value are accepted
# automatically; lower agreement goes to a reviewer for arbitration.
CONSISTENCY_THRESHOLD = 0.8


def annotation_json(db, obj):
    result = serialize(obj)
    result.update(annotator=user_ref(db, obj.annotator_id), reviewed_by=user_ref(db, obj.reviewed_by_id))
    return result


def task_json(db, obj):
    data = {**serialize(obj), "assignee": user_ref(db, obj.assignee_id)}
    image = db.get(m.Image, obj.image_id)
    if image:
        data.update(filename=image.filename, class_label=image.class_label)
    assignments = list(
        db.scalars(select(m.AnnotationAssignment).where(m.AnnotationAssignment.task_id == obj.id))
    )
    if obj.required_annotators > 1:
        data["participants"] = [
            {"id": a.annotator_id, **(user_ref(db, a.annotator_id) or {})} for a in assignments
        ]
        data["submitted_count"] = sum(a.status == "submitted" for a in assignments)
    else:
        data["participants"] = [user_ref(db, obj.assignee_id)] if obj.assignee_id else []
        data["submitted_count"] = 1 if obj.status in ("submitted", "approved") else 0
    return data


def is_participant(db, task, user):
    if task.assignee_id == user.id:
        return True
    if task.required_annotators <= 1:
        return False
    return (
        db.scalar(
            select(m.AnnotationAssignment.id).where(
                m.AnnotationAssignment.task_id == task.id,
                m.AnnotationAssignment.annotator_id == user.id,
            )
        )
        is not None
    )


def sync_assignment(db, task, user, annotation_id, status, submitted=False):
    assignment = db.scalar(
        select(m.AnnotationAssignment)
        .where(
            m.AnnotationAssignment.task_id == task.id,
            m.AnnotationAssignment.annotator_id == user.id,
        )
        .with_for_update()
    )
    if assignment is None:
        assignment = m.AnnotationAssignment(task_id=task.id, annotator_id=user.id)
        db.add(assignment)
        db.flush()
    if annotation_id is not None:
        assignment.annotation_id = annotation_id
    assignment.status = status
    if submitted:
        assignment.submitted_at = now()
    return assignment


def close_assignments(db, task, winner_id):
    for assignment in db.scalars(
        select(m.AnnotationAssignment).where(m.AnnotationAssignment.task_id == task.id)
    ):
        assignment.status = "approved" if assignment.annotation_id == winner_id else "rejected"


def mask_iou(left, right):
    a, b = rle_decode(left), rle_decode(right)
    union = int((a | b).sum())
    return 1.0 if union == 0 else float((a & b).sum()) / union


def evaluate_consistency(db, task, user, request):
    pending = list(
        db.scalars(
            select(m.Annotation)
            .where(m.Annotation.image_id == task.image_id, m.Annotation.status == "pending")
            .order_by(m.Annotation.version)
        )
    )
    if len(pending) < task.required_annotators:
        return
    chosen = pending[0]
    iou = mask_iou(chosen.mask_rle, pending[1].mask_rle)
    passed = iou >= CONSISTENCY_THRESHOLD
    task.consistency = {
        "iou": round(iou, 4),
        "threshold": CONSISTENCY_THRESHOLD,
        "auto": passed,
        "versions": [item.version for item in pending],
    }
    if passed:
        db.execute(
            update(m.Annotation)
            .where(
                m.Annotation.image_id == task.image_id,
                m.Annotation.status == "approved",
                m.Annotation.id != chosen.id,
            )
            .values(status="rejected")
        )
        db.flush()
        for other in pending[1:]:
            other.status = "rejected"
        chosen.status = "approved"
        task.status, task.finished_at, task.annotation_id = "approved", now(), chosen.id
        close_assignments(db, task, chosen.id)
        audit(db, user, "annotation.consistency.auto", chosen, request, task.consistency)
    else:
        task.status = "submitted"
    db.flush()


def save_annotation(db, body, user, *, enforce_owner=True, link_task=True):
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
    if enforce_owner and (not task or not is_participant(db, task, user)):
        raise APIError(409, "请先领取本人标注任务")
    if link_task is False:
        task = None
    if task and task.status == "submitted":
        raise APIError(409, "待审核标注不能继续编辑")
    limit = task.required_annotators if task else 1
    if db.scalar(
        select(m.Annotation.id).where(
            m.Annotation.image_id == image.id,
            m.Annotation.annotator_id == user.id,
            m.Annotation.status == "pending",
        )
    ):
        raise APIError(409, "本人已有待审核版本")
    others = db.scalar(
        select(func.count())
        .select_from(m.Annotation)
        .where(
            m.Annotation.image_id == image.id,
            m.Annotation.annotator_id != user.id,
            m.Annotation.status == "pending",
        )
    )
    if others >= limit:
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
        if task.required_annotators > 1:
            sync_assignment(db, task, user, obj.id, "in_progress")
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
    task = get(db, cls, id)
    if cls is m.AnnotationTask and task.required_annotators > 1:
        sync_assignment(db, task, user, None, "in_progress")
    return task


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
            image_id=image.id,
            dataset_version_id=body.dataset_version_id,
            priority=body.priority,
            required_annotators=body.required_annotators,
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
        stmt = stmt.where(
            or_(
                m.AnnotationTask.assignee_id == user.id,
                m.AnnotationTask.id.in_(
                    select(m.AnnotationAssignment.task_id).where(
                        m.AnnotationAssignment.annotator_id == user.id
                    )
                ),
            )
        )
    return page(request, db, stmt, m.AnnotationTask, lambda x: task_json(db, x))


@router.post("/annotation-tasks/{id}/claim")
def claim_task(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("annotation:edit"))
):
    obj = claim(db, m.AnnotationTask, id, user)
    audit(db, user, "annotation.claim", obj, request)
    return reply(request, task_json(db, obj))


@router.post("/annotation-tasks/{id}/join")
def join_task(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("annotation:edit"))
):
    task = get(db, m.AnnotationTask, id, lock=True)
    if task.required_annotators <= 1:
        raise APIError(409, "单人任务请直接领取")
    if task.status not in ("pending", "in_progress"):
        raise APIError(409, "任务已结束")
    if is_participant(db, task, user):
        raise APIError(409, "已在任务中")
    count = db.scalar(
        select(func.count())
        .select_from(m.AnnotationAssignment)
        .where(m.AnnotationAssignment.task_id == task.id)
    )
    if count >= task.required_annotators:
        raise APIError(409, "任务人数已满")
    sync_assignment(db, task, user, None, "in_progress")
    if task.status == "pending":
        task.status, task.claimed_at = "in_progress", now()
        if not task.assignee_id:
            task.assignee_id = user.id
    audit(db, user, "annotation.join", task, request)
    db.flush()
    return reply(request, task_json(db, task))


@router.post("/annotation-tasks/{id}/release")
def release_task(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("annotation:edit"))
):
    obj = get(db, m.AnnotationTask, id, lock=True)
    if obj.required_annotators > 1:
        assignment = db.scalar(
            select(m.AnnotationAssignment).where(
                m.AnnotationAssignment.task_id == obj.id,
                m.AnnotationAssignment.annotator_id == user.id,
            )
        )
        if assignment is None:
            raise APIError(409, "不在该标注任务中")
        if assignment.status == "submitted":
            raise APIError(409, "已提交的标注不能释放，请等待审核")
        db.delete(assignment)
        if obj.assignee_id == user.id:
            remaining = db.scalar(
                select(m.AnnotationAssignment.annotator_id).where(
                    m.AnnotationAssignment.task_id == obj.id,
                    m.AnnotationAssignment.annotator_id != user.id,
                )
            )
            obj.assignee_id, obj.claimed_at = remaining, now() if remaining else None
            if not remaining and obj.status == "in_progress":
                obj.status = "pending"
        audit(db, user, "annotation.release", obj, request)
        db.flush()
        return reply(request, task_json(db, obj))
    if obj.status != "in_progress" or obj.assignee_id != user.id:
        raise APIError(409, "只能释放本人进行中的任务")
    obj.status, obj.assignee_id, obj.claimed_at = "pending", None, None
    audit(db, user, "annotation.release", obj, request)
    db.flush()
    return reply(request, task_json(db, obj))


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
    task = db.scalar(
        select(m.AnnotationTask)
        .where(
            m.AnnotationTask.image_id == obj.image_id,
            m.AnnotationTask.status != "approved",
        )
        .with_for_update()
    )
    if obj.status != "draft" or not task:
        raise APIError(409, "只能提交当前任务的最新草稿")
    if task.required_annotators > 1:
        assignment = db.scalar(
            select(m.AnnotationAssignment)
            .where(
                m.AnnotationAssignment.task_id == task.id,
                m.AnnotationAssignment.annotator_id == user.id,
            )
            .with_for_update()
        )
        if not assignment or assignment.annotation_id != id:
            raise APIError(409, "只能提交本人当前草稿")
        obj.status = "pending"
        assignment.status, assignment.submitted_at = "submitted", now()
        if body and body.note is not None:
            obj.note = body.note
        audit(db, user, "annotation.submit", obj, request)
        db.flush()
        evaluate_consistency(db, task, user, request)
        return reply(request, annotation_json(db, obj))
    if task.annotation_id != id or task.assignee_id != user.id:
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
        db.execute(
            update(m.Annotation)
            .where(
                m.Annotation.image_id == obj.image_id,
                m.Annotation.status == "pending",
                m.Annotation.id != id,
            )
            .values(status="rejected")
        )
        db.flush()
    obj.status = "approved" if body.decision == "approve" else "draft"
    obj.reviewed_by_id, obj.review_comment, obj.reviewed_at = user.id, body.comment, now()
    db.add(m.AnnotationReview(annotation_id=id, reviewer_id=user.id, **body.model_dump()))
    task = db.scalar(
        select(m.AnnotationTask)
        .where(
            m.AnnotationTask.image_id == obj.image_id,
            m.AnnotationTask.status != "approved",
        )
        .with_for_update()
    )
    if task:
        task.status = "approved" if body.decision == "approve" else "in_progress"
        task.finished_at = now() if body.decision == "approve" else None
        if task.required_annotators > 1:
            assignment = db.scalar(
                select(m.AnnotationAssignment).where(
                    m.AnnotationAssignment.task_id == task.id,
                    m.AnnotationAssignment.annotator_id == obj.annotator_id,
                )
            )
            if assignment:
                assignment.status = "approved" if body.decision == "approve" else "in_progress"
                assignment.submitted_at = now() if body.decision == "approve" else None
            if body.decision == "approve":
                close_assignments(db, task, id)
    audit(db, user, "annotation.review", obj, request, body.model_dump())
    db.flush()
    return reply(request, annotation_json(db, obj))


@router.get("/images/{id}/annotations")
def history(id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    get(db, m.Image, id)
    stmt = select(m.Annotation).where(m.Annotation.image_id == id)
    if request.query_params.get("status"):
        stmt = stmt.where(m.Annotation.status == request.query_params["status"])
    return page(request, db, stmt, m.Annotation, lambda x: annotation_json(db, x))
