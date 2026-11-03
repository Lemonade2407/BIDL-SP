import logging
import re

import jwt
from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from redis import Redis
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from starlette.exceptions import HTTPException

from . import routes_admin, routes_annotations, routes_auth, routes_data, routes_models, routes_screening
from .common import APIError
from .config import DISCLAIMER, settings
from .db import engine, uid
from .storage import storage

logger = logging.getLogger(__name__)
app = FastAPI(title="BIDL-SP", version="1.1.0", description=DISCLAIMER)


class BodyLimitMiddleware:
    """Bound multipart spooling as well as JSON, including chunked uploads."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = (
            settings.max_zip_mb if scope["path"].endswith("/imports") else settings.max_upload_mb
        ) * 1024**2
        received = 0

        async def bounded_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > limit:
                raise HTTPException(413, "请求体超过大小上限")
            return message

        headers = dict(scope.get("headers", []))
        try:
            too_large = int(headers.get(b"content-length", b"0")) > limit
        except ValueError:
            too_large = True
        if too_large:
            response = JSONResponse(
                {
                    "code": "PAYLOAD_TOO_LARGE",
                    "message": "请求体超过大小上限",
                    "request_id": scope.get("state", {}).get("request_id", "req_" + uid()),
                    "details": [],
                },
                status_code=413,
            )
            return await response(scope, receive, send)
        await self.app(scope, bounded_receive, send)


app.add_middleware(BodyLimitMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-Id"],
    expose_headers=["X-Request-Id", "Idempotent-Replay"],
)


def error(request, status, code, message, details=None):
    return JSONResponse(
        {"code": code, "message": message, "request_id": request.state.request_id, "details": details or []},
        status_code=status,
    )


@app.middleware("http")
async def request_context(request: Request, call_next):
    supplied = request.headers.get("X-Request-Id", "")
    request.state.request_id = supplied if re.fullmatch(r"[A-Za-z0-9_.-]{1,64}", supplied) else "req_" + uid()
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("Unhandled request %s", request.state.request_id)
        response = error(request, 500, "INTERNAL_ERROR", "服务内部错误，请使用 request_id 联系管理员")
    response.headers["X-Request-Id"] = request.state.request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(APIError)
async def api_error(request, exc):
    return error(request, exc.status, exc.code, exc.message, exc.details)


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return error(
        request,
        422,
        "VALIDATION_ERROR",
        "参数校验失败",
        [{"field": ".".join(str(p) for p in item["loc"]), "reason": item["msg"]} for item in exc.errors()],
    )


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return error(
        request,
        exc.status_code,
        {413: "PAYLOAD_TOO_LARGE", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "VALIDATION_ERROR"
        ),
        str(exc.detail),
    )


@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    return error(request, 409, "CONFLICT", "资源已存在或状态发生并发变化，请刷新重试")


@app.exception_handler(SQLAlchemyError)
async def db_error(request, exc):
    logger.error("Database unavailable for request %s", request.state.request_id)
    return error(request, 503, "DEPENDENCY_UNAVAILABLE", "数据库暂不可用")


router = APIRouter(prefix="/api/v1")
for module in (routes_auth, routes_data, routes_annotations, routes_models, routes_screening, routes_admin):
    router.include_router(module.router)


@router.get("/healthz")
def health():
    return {"status": "ok"}


@router.get("/readyz")
def ready():
    checks = {}
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM alembic_version"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "failed"
    try:
        checks["redis"] = (
            "disabled-local-mode"
            if settings.task_eager and settings.rate_limit_backend == "memory"
            else "ok"
            if Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2).ping()
            else "failed"
        )
    except Exception:
        checks["redis"] = "failed"
    try:
        checks["minio"] = "ok" if storage.health() else "failed"
    except Exception:
        checks["minio"] = "failed"
    good = "failed" not in checks.values()
    return JSONResponse(
        {"status": "ok" if good else "unavailable", "checks": checks}, status_code=200 if good else 503
    )


@router.get("/files/{signed_token}", include_in_schema=False)
def local_file(signed_token: str):
    if not storage.local:
        raise APIError(404, "不存在")
    try:
        payload = jwt.decode(
            signed_token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"require": ["kind", "exp", "bucket", "key"]},
        )
        if payload["kind"] != "object":
            raise ValueError()
        path = storage.path(payload["bucket"], payload["key"])
        if not path.is_file():
            raise APIError(404, "对象不存在")
        return FileResponse(path)
    except (jwt.PyJWTError, ValueError, KeyError):
        raise APIError(403, "下载链接无效或已过期") from None


app.include_router(router)
