from fastapi import APIRouter, Depends, Request
from sqlalchemy import func, select, update
from sqlalchemy.orm import aliased

from . import models as m
from .common import APIError, page, reply, serialize
from .db import get_db, now
from .security import current_user, has

router = APIRouter()


@router.get("/notifications")
def notifications(request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    stmt = select(m.Notification).where(m.Notification.user_id == user.id)
    unread = request.query_params.get("unread")
    if unread is not None:
        if unread not in ("true", "false"):
            raise APIError(422, "unread 必须为 true/false")
        stmt = stmt.where(
            m.Notification.read_at.is_(None) if unread == "true" else m.Notification.read_at.is_not(None)
        )
    return page(request, db, stmt, m.Notification)


@router.get("/notifications/unread-count")
def unread_count(request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    count = db.scalar(
        select(func.count())
        .select_from(m.Notification)
        .where(m.Notification.user_id == user.id, m.Notification.read_at.is_(None))
    )
    return reply(request, {"count": count})


@router.post("/notifications/read-all")
def read_all(request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    count = db.execute(
        update(m.Notification)
        .where(m.Notification.user_id == user.id, m.Notification.read_at.is_(None))
        .values(read_at=now())
    ).rowcount
    return reply(request, {"updated": count})


@router.post("/notifications/{id}/read")
def read_one(id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    obj = db.scalar(
        select(m.Notification)
        .where(m.Notification.id == id, m.Notification.user_id == user.id)
        .with_for_update()
    )
    if obj is None:
        raise APIError(404, "通知不存在")
    if obj.read_at is None:
        obj.read_at = now()
    db.flush()
    return reply(request, serialize(obj))


@router.get("/todos")
def todos(request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    """Live actionable rows; reading a notification never completes its business task."""
    items = []
    if has(user, "annotation:review"):
        for row in db.scalars(
            select(m.Annotation).where(m.Annotation.status == "pending", m.Annotation.annotator_id != user.id)
        ):
            items.append(
                {"type": "annotation.pending_review", "id": row.id, "link": f"/annotation/review/{row.id}"}
            )
    if has(user, "report:sign"):
        for row in db.scalars(
            select(m.Report).where(m.Report.status == "pending_review", m.Report.author_id != user.id)
        ):
            items.append({"type": "report.pending_sign", "id": row.id, "link": f"/reports/{row.id}"})
    for row in db.scalars(
        select(m.ScreenTask).where(m.ScreenTask.status == "returned", m.ScreenTask.assignee_id == user.id)
    ):
        items.append({"type": "screen.returned", "id": row.id, "link": f"/screening/studies/{row.study_id}"})
    for cls, owner, link in (
        (m.InferenceTask, m.InferenceTask.requested_by, "/screening/worklist"),
        (m.EvaluationJob, m.EvaluationJob.created_by, "/models"),
    ):
        for row in db.scalars(select(cls).where(cls.status == "failed", owner == user.id)):
            newer = aliased(cls)
            conditions = [
                newer.created_at > row.created_at,
                newer.model_version_id == row.model_version_id,
                newer.status.in_(["queued", "running", "succeeded"]),
            ]
            if cls is m.InferenceTask:
                conditions += [newer.image_id == row.image_id, newer.requested_by == user.id]
            else:
                conditions += [
                    newer.dataset_version_id == row.dataset_version_id,
                    newer.created_by == user.id,
                ]
            if db.scalar(select(newer.id).where(*conditions).limit(1)):
                continue
            items.append(
                {"type": "task.failed", "object_type": cls.__tablename__, "id": row.id, "link": link}
            )
    return reply(request, {"items": items, "total": len(items)})
