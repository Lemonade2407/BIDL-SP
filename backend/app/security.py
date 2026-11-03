import threading
import time
from collections import defaultdict
from datetime import timedelta

import bcrypt
import jwt
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from redis import Redis
from sqlalchemy import select

from .common import APIError
from .config import settings
from .db import get_db, now, uid
from .models import RevokedToken, User

PERMISSIONS = {
    "data_engineer": {
        "data:import",
        "dataset:write",
        "image:read",
        "image:download",
        "annotation:manage",
        "inference:create",
        "stats:read",
    },
    "annotator": {"image:read", "annotation:edit", "stats:read"},
    "screener": {"image:read", "inference:create", "screening:manage", "report:draft", "stats:read"},
    "reviewer": {"image:read", "annotation:review", "report:sign", "stats:read"},
}
bearer = HTTPBearer(auto_error=False)
_attempts = defaultdict(list)
_limit_lock = threading.Lock()


def hash_password(password):
    if len(password.encode()) > 72:
        raise APIError(422, "密码 UTF-8 编码不能超过 72 字节")
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password, hashed):
    return len(password.encode()) <= 72 and bcrypt.checkpw(password.encode(), hashed.encode())


def token(user):
    issued = now()
    return jwt.encode(
        {
            "sub": user.id,
            "roles": user.roles,
            "jti": uid(),
            "iat": issued,
            "exp": issued + timedelta(hours=settings.jwt_hours),
            "ver": user.token_version,
            "kind": "access",
        },
        settings.jwt_secret,
        algorithm="HS256",
    )


def current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(bearer),
    db=Depends(get_db, scope="function"),
):
    try:
        if credentials is None:
            raise ValueError()
        payload = jwt.decode(
            credentials.credentials,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["sub", "exp", "iat", "jti", "ver", "kind"]},
        )
        if payload["kind"] != "access":
            raise ValueError()
        user = db.get(User, payload["sub"])
        if not user or user.status != "active" or user.token_version != payload["ver"]:
            raise ValueError()
        if db.scalar(select(RevokedToken.id).where(RevokedToken.jti == payload["jti"])):
            raise ValueError()
        request.state.claims = payload
        return user
    except (jwt.PyJWTError, ValueError, KeyError):
        raise APIError(401, "请重新登录") from None


def has(user, permission):
    return "admin" in user.roles or any(permission in PERMISSIONS.get(role, set()) for role in user.roles)


def require(*permissions):
    def dependency(user=Depends(current_user)):
        if not any(has(user, p) for p in permissions):
            raise APIError(403, "没有此操作权限")
        return user

    return dependency


def limit_login(ip):
    if settings.rate_limit_backend == "memory":
        with _limit_lock:
            stamp = time.monotonic()
            _attempts[ip] = [t for t in _attempts[ip] if stamp - t < 60]
            if len(_attempts[ip]) >= 5:
                raise APIError(429, "登录过于频繁，请一分钟后重试")
            _attempts[ip].append(stamp)
    else:
        try:
            client = Redis.from_url(settings.redis_url, socket_timeout=2)
            count = client.eval(
                "local n=redis.call('INCR',KEYS[1]); if n==1 then redis.call('EXPIRE',KEYS[1],60) end; return n",
                1,
                "login:" + ip,
            )
        except Exception:
            raise APIError(503, "认证限流依赖不可用") from None
        if count > 5:
            raise APIError(429, "登录过于频繁，请一分钟后重试")
