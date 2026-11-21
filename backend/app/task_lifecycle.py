"""Recover human work without discarding submitted dual annotations."""

from datetime import timedelta

from sqlalchemy import select

from . import models as m
from .common import audit
from .config import settings
from .db import now
from .notifications import notify, recipients


def release_work(db, task, user_id=None):
    owners = []
    if isinstance(task, m.AnnotationTask) and task.required_annotators > 1:
        assignments = list(
            db.scalars(
                select(m.AnnotationAssignment)
                .where(m.AnnotationAssignment.task_id == task.id)
                .with_for_update()
            )
        )
        for assignment in assignments:
            if assignment.status == "in_progress" and (user_id is None or assignment.annotator_id == user_id):
                owners.append(assignment.annotator_id)
                db.delete(assignment)
        remaining = [a for a in assignments if a not in db.deleted]
        task.assignee_id = remaining[0].annotator_id if remaining else None
        task.claimed_at = remaining[0].created_at if remaining else None
        task.status = "in_progress" if remaining else "pending"
    elif task.assignee_id and (user_id is None or task.assignee_id == user_id):
        owners.append(task.assignee_id)
        task.assignee_id, task.claimed_at = None, None
        # Re-inference still has to pass the returned-task claim gate after account disable.
        task.status = (
            "returned" if isinstance(task, m.ScreenTask) and task.status == "returned" else "pending"
        )
        if isinstance(task, m.ScreenTask):
            db.get(m.Study, task.study_id).status = task.status
    task.overdue_at = None
    return owners


def release_user_tasks(db, user_id, actor, request):
    released = []
    for cls in (m.AnnotationTask, m.ScreenTask):
        for task in db.scalars(
            select(cls).where(cls.status.in_(["in_progress", "returned"])).order_by(cls.id).with_for_update()
        ):
            if isinstance(task, m.AnnotationTask) and task.required_annotators > 1:
                involved = db.scalar(
                    select(m.AnnotationAssignment.id).where(
                        m.AnnotationAssignment.task_id == task.id,
                        m.AnnotationAssignment.annotator_id == user_id,
                        m.AnnotationAssignment.status == "in_progress",
                    )
                )
            else:
                involved = task.assignee_id == user_id
            if not involved:
                continue
            owners = release_work(db, task, user_id)
            if owners:
                released.append(task.id)
                audit(db, actor, "task.release_disabled", task, request, {"user_id": user_id})
                notify(
                    db,
                    recipients(db, "user:manage"),
                    "task.released",
                    task,
                    "已释放停用账号的任务",
                    link="/annotation/tasks" if cls is m.AnnotationTask else "/screening/worklist",
                )
    return released


def recover_overdue(db):
    stamp = now()
    for cls, hours in (
        (m.AnnotationTask, settings.annotation_sla_hours),
        (m.ScreenTask, settings.screening_sla_hours),
    ):
        for task in db.scalars(
            select(cls)
            .where(cls.status == "in_progress", cls.claimed_at < stamp - timedelta(hours=hours))
            .order_by(cls.id)
            .with_for_update(skip_locked=True)
        ):
            owners = [task.assignee_id]
            if cls is m.AnnotationTask and task.required_annotators > 1:
                owners = list(
                    db.scalars(
                        select(m.AnnotationAssignment.annotator_id).where(
                            m.AnnotationAssignment.task_id == task.id,
                            m.AnnotationAssignment.status == "in_progress",
                        )
                    )
                )
                if not owners:  # All contributions are submitted; nothing to reclaim.
                    continue
            if task.overdue_at is None:
                task.overdue_at = stamp
                audit(db, None, "task.overdue", task, detail={"assignee_ids": owners, "sla_hours": hours})
                notify(
                    db,
                    owners + recipients(db, "user:manage"),
                    "task.overdue",
                    task,
                    "任务已逾期",
                    "请在宽限期内完成，否则将释放任务",
                    "/annotation/tasks" if cls is m.AnnotationTask else "/screening/worklist",
                    version=str(task.claimed_at),
                )
            else:
                overdue = task.overdue_at
                if overdue.tzinfo is None:
                    overdue = overdue.replace(tzinfo=stamp.tzinfo)
                if overdue + timedelta(hours=settings.task_release_grace_hours) <= stamp:
                    owners = release_work(db, task)
                    audit(
                        db, None, "task.timeout", task, detail={"assignee_ids": owners, "status": task.status}
                    )
                    notify(
                        db,
                        owners + recipients(db, "user:manage"),
                        "task.released",
                        task,
                        "逾期任务已释放",
                        link="/annotation/tasks" if cls is m.AnnotationTask else "/screening/worklist",
                    )
