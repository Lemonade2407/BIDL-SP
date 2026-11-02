import hashlib
import json
from datetime import datetime, timezone

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import func, inspect, select

from . import models as m
from .db import now


class APIError(Exception):
    def __init__(self, status, message, code=None, details=None):
        self.status = status
        self.message = message
        self.code = code or {
            401: "UNAUTHENTICATED",
            403: "FORBIDDEN",
            404: "NOT_FOUND",
            409: "CONFLICT",
            413: "PAYLOAD_TOO_LARGE",
            415: "UNSUPPORTED_MEDIA_TYPE",
            422: "VALIDATION_ERROR",
            429: "RATE_LIMITED",
            503: "DEPENDENCY_UNAVAILABLE",
        }.get(status, "INTERNAL_ERROR")
        self.details = details or []


def get(db, cls, id, lock=False):
    stmt = select(cls).where(cls.id == id)
    if lock:
        stmt = stmt.with_for_update()
    row = db.scalar(stmt)
    if row is None:
        raise APIError(404, "资源不存在")
    return row


def serialize(obj):
    if obj is None:
        return None
    excluded = {"password_hash", "token_version", "upload_key"}
    result = {c.key: getattr(obj, c.key) for c in inspect(obj).mapper.column_attrs if c.key not in excluded}
    for key, value in result.items():
        if isinstance(value, datetime) and value.tzinfo is None:
            result[key] = value.replace(tzinfo=timezone.utc)
    return jsonable_encoder(result)


def reply(request, data, status=200, **meta):
    return JSONResponse(
        jsonable_encoder({"data": data, "meta": {"request_id": request.state.request_id, **meta}}),
        status_code=status,
    )


def page(request: Request, db, stmt, cls, render=serialize):
    params = request.query_params
    try:
        number = int(params.get("page", 1))
        size = int(params.get("page_size", 20))
        if number < 1 or size < 1 or size > 100:
            raise ValueError()
    except ValueError:
        raise APIError(422, "page >= 1; page_size between 1 and 100") from None
    sort = params.get("sort") or "-created_at"
    allowed = {"created_at", "updated_at", "id", "priority", "version", "username", "name"}
    field = sort.lstrip("-")
    if field not in allowed or not hasattr(cls, field):
        raise APIError(422, "非法排序字段")
    column = getattr(cls, field)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.scalars(
        stmt.order_by(column.desc() if sort.startswith("-") else column, cls.id)
        .offset((number - 1) * size)
        .limit(size)
    ).all()
    return reply(request, [render(row) for row in rows], page=number, page_size=size, total=total)


def audit(db, user, action, obj, request=None, detail=None, object_type=None):
    db.add(
        m.AuditLog(
            actor_id=user.id if user else None,
            action=action,
            object_type=object_type or obj.__tablename__,
            object_id=str(obj.id),
            detail=detail or {},
            ip=request.client.host if request and request.client else None,
            request_id=request.state.request_id if request else None,
            created_at=now(),
        )
    )


def fingerprint(payload):
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()


def replay(request, db, user, payload):
    key = request.headers.get("Idempotency-Key")
    if key is None:
        return None
    if not 1 <= len(key) <= 128:
        raise APIError(422, "Idempotency-Key 必须为 1–128 字符")
    previous = db.scalar(
        select(m.Idempotency).where(
            m.Idempotency.actor_id == user.id,
            m.Idempotency.route == request.url.path,
            m.Idempotency.key == key,
        )
    )
    if previous:
        if previous.digest != fingerprint(payload):
            raise APIError(409, "同一幂等键请求内容不同")
        response = reply(request, previous.response, previous.status_code)
        response.headers["Idempotent-Replay"] = "true"
        return response


def remember(request, db, user, payload, response, status=202):
    key = request.headers.get("Idempotency-Key")
    if key:
        db.add(
            m.Idempotency(
                actor_id=user.id,
                route=request.url.path,
                key=key,
                digest=fingerprint(payload),
                response=jsonable_encoder(response),
                status_code=status,
            )
        )


def queue(db, kind, obj):
    db.flush()
    db.add(m.Outbox(kind=kind, object_id=obj.id))


def user_ref(db, id):
    user = db.get(m.User, id) if id else None
    return {"id": user.id, "display_name": user.display_name} if user else None
