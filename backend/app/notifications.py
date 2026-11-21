"""Best-effort notifications isolated by savepoint, committed with the business event."""

import logging

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError

from . import models as m
from .common import audit, fingerprint
from .security import has

logger = logging.getLogger(__name__)


def recipients(db, permission, exclude=None):
    return [
        u.id
        for u in db.scalars(select(m.User).where(m.User.status == "active"))
        if u.id != exclude and has(u, permission)
    ]


def notify(db, user_ids, kind, obj, title, body="", link="/dashboard", version=None):
    # Flush business writes BEFORE entering the recovery boundary: never swallow their errors.
    db.flush()
    key = fingerprint([kind, obj.id, version if version is not None else str(obj.updated_at)])
    for user_id in sorted(set(u for u in user_ids if u)):
        try:
            with db.begin_nested():
                if db.scalar(
                    select(m.Notification.id).where(
                        m.Notification.user_id == user_id, m.Notification.dedupe_key == key
                    )
                ):
                    continue
                notice = m.Notification(
                    user_id=user_id,
                    type=kind,
                    title=title,
                    body=body,
                    object_type=obj.__tablename__,
                    object_id=obj.id,
                    link=link,
                    dedupe_key=key,
                )
                db.add(notice)
                db.flush()
                audit(
                    db,
                    None,
                    "notification.send",
                    notice,
                    detail={"type": kind, "object_type": obj.__tablename__, "object_id": obj.id},
                )
        except IntegrityError:
            logger.info("Duplicate or unavailable notification recipient: %s", user_id)
        except SQLAlchemyError:
            logger.exception("Notification insert failed; business transaction remains usable")


def notify_failure(db, obj):
    owner = obj.requested_by if isinstance(obj, m.InferenceTask) else obj.created_by
    link = "/models" if isinstance(obj, m.EvaluationJob) else "/screening/worklist"
    notify(
        db,
        [owner],
        "task.failed",
        obj,
        "任务失败，请处理",
        (obj.error or {}).get("message", ""),
        link,
        version="failed",
    )
