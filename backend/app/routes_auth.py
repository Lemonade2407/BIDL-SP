from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import or_, select

from . import models as m
from . import schemas as s
from .common import APIError, audit, get, page, reply, serialize
from .config import settings
from .db import get_db, now
from .security import current_user, hash_password, limit_login, require, token, verify_password

router = APIRouter()


@router.post("/auth/login")
def login(body: s.Login, request: Request, db=Depends(get_db, scope="function")):
    limit_login(request.client.host)
    user = db.scalar(select(m.User).where(m.User.username == body.username))
    if not user or user.status != "active" or not verify_password(body.password, user.password_hash):
        raise APIError(401, "用户名或密码错误")
    user.last_login_at = now()
    audit(db, user, "auth.login", user, request)
    return reply(
        request,
        {
            "access_token": token(user),
            "token_type": "Bearer",
            "expires_in": settings.jwt_hours * 3600,
            "user": serialize(user),
        },
    )


@router.get("/auth/me")
def me(request: Request, user=Depends(current_user)):
    return reply(request, serialize(user))


@router.post("/auth/logout", status_code=204)
def logout(request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    claims = request.state.claims
    db.add(m.RevokedToken(jti=claims["jti"], expires_at=datetime.fromtimestamp(claims["exp"], timezone.utc)))
    audit(db, user, "auth.logout", user, request)
    return Response(status_code=204)


@router.post("/auth/password", status_code=204)
def password(
    body: s.PasswordChange, request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)
):
    if not verify_password(body.old_password, user.password_hash):
        raise APIError(401, "旧密码错误")
    user.password_hash = hash_password(body.new_password)
    user.token_version += 1
    audit(db, user, "auth.password", user, request)
    return Response(status_code=204)


@router.get("/users")
def users(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("user:manage"))):
    stmt = select(m.User)
    q, status, role = (request.query_params.get(k) for k in ("q", "status", "role"))
    if q:
        stmt = stmt.where(or_(m.User.username.contains(q), m.User.display_name.contains(q)))
    if status:
        stmt = stmt.where(m.User.status == status)
    if role:
        ids = [u.id for u in db.scalars(select(m.User)) if role in u.roles]
        stmt = stmt.where(m.User.id.in_(ids))
    return page(request, db, stmt, m.User)


@router.post("/users", status_code=201)
def create_user(
    body: s.UserCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("user:manage")),
):
    obj = m.User(**body.model_dump(exclude={"password"}), password_hash=hash_password(body.password))
    db.add(obj)
    db.flush()
    audit(db, user, "user.create", obj, request)
    return reply(request, serialize(obj), 201)


@router.patch("/users/{id}")
def update_user(
    id: str,
    body: s.UserPatch,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("user:manage")),
):
    # Lock every active user in stable order, so two admins cannot simultaneously remove each other.
    active = list(
        db.scalars(select(m.User).where(m.User.status == "active").order_by(m.User.id).with_for_update())
    )
    obj = get(db, m.User, id)
    changes = body.model_dump(exclude_none=True)
    removing = changes.get("status") == "disabled" or ("roles" in changes and "admin" not in changes["roles"])
    if (
        "admin" in obj.roles
        and obj.status == "active"
        and removing
        and sum("admin" in u.roles for u in active) <= 1
    ):
        raise APIError(409, "不能禁用或移除最后一个管理员")
    if "password" in changes:
        obj.password_hash = hash_password(changes.pop("password"))
    for key, value in changes.items():
        setattr(obj, key, value)
    obj.token_version += 1
    audit(db, user, "user.update", obj, request, {"fields": list(changes)})
    db.flush()
    return reply(request, serialize(obj))
