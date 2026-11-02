import hashlib
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import or_, select

from . import models as m
from . import schemas as s
from .common import APIError, audit, get, page, queue, remember, replay, reply, serialize
from .config import settings
from .data_service import freeze, validate_archive
from .db import get_db, uid
from .security import current_user, has, require
from .storage import storage

router = APIRouter()


def image_json(db, image):
    result = serialize(image)
    annotation = db.scalar(
        select(m.Annotation).where(m.Annotation.image_id == image.id).order_by(m.Annotation.version.desc())
    )
    result.update(
        mask_available=bool(image.mask_object_key),
        annotation_status=annotation.status if annotation else "none",
        thumbnail_url=storage.url("bidlsp-curated", image.cache_key) if image.cache_key else None,
    )
    for field in ("object_key", "mask_object_key", "cache_key", "preview_key"):
        result.pop(field, None)
    return result


def version_json(obj, allow_manifest=False):
    result = serialize(obj)
    result["manifest_url"] = (
        storage.url("bidlsp-dataset", obj.manifest_key) if obj.manifest_key and allow_manifest else None
    )
    return result


@router.get("/datasets")
def datasets(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("dataset:write"))):
    return page(request, db, select(m.Dataset), m.Dataset)


@router.post("/datasets", status_code=201)
def create_dataset(
    body: s.DatasetCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("dataset:write")),
):
    obj = m.Dataset(**body.model_dump(), created_by=user.id)
    db.add(obj)
    db.flush()
    audit(db, user, "dataset.create", obj, request)
    return reply(request, serialize(obj), 201)


@router.post("/datasets/{id}/imports", status_code=202)
def create_import(
    id: str,
    request: Request,
    file: UploadFile = File(...),
    class_hint: Literal["benign", "malignant", "normal"] | None = Form(None),
    db=Depends(get_db, scope="function"),
    user=Depends(require("data:import")),
):
    get(db, m.Dataset, id)
    if (
        not file.filename
        or not file.filename.lower().endswith(".zip")
        or file.content_type
        not in ("application/zip", "application/x-zip-compressed", "application/octet-stream")
    ):
        raise APIError(415, "请上传 ZIP")
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=settings.work_dir, suffix=".zip", delete=False) as stream:
        path = Path(stream.name)
        digest, size = hashlib.sha256(), 0
        try:
            while chunk := file.file.read(1024 * 1024):
                size += len(chunk)
                if size > settings.max_zip_mb * 1024**2:
                    raise APIError(413, "ZIP 上传超限")
                digest.update(chunk)
                stream.write(chunk)
        except Exception:
            stream.close()
            path.unlink(missing_ok=True)
            raise
    try:
        validate_archive(path)
        payload = {"dataset_id": id, "sha256": digest.hexdigest(), "class_hint": class_hint}
        previous = replay(request, db, user, payload)
        if previous:
            return previous
        job = m.ImportJob(
            id=uid(),
            dataset_id=id,
            created_by=user.id,
            class_hint=class_hint,
            upload_key=f"uploads/{uid()}.zip",
        )
        storage.put_file("bidlsp-raw", job.upload_key, path, "application/zip")
        db.add(job)
        queue(db, "import", job)
        result = {"job_id": job.id, "status": job.status, "created_at": job.created_at}
        remember(request, db, user, payload, result)
        audit(db, user, "data.import", job, request)
        return reply(request, result, 202)
    finally:
        path.unlink(missing_ok=True)


@router.get("/imports/{job_id}")
def import_progress(
    job_id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("data:import"))
):
    return reply(request, serialize(get(db, m.ImportJob, job_id)))


@router.get("/images")
def images(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("image:read"))):
    stmt = select(m.Image)
    p = request.query_params
    for field in ("class_label", "source", "study_id", "dataset_id"):
        if p.get(field):
            stmt = stmt.where(getattr(m.Image, field) == p[field])
    if p.get("dataset_version_id"):
        stmt = stmt.where(
            m.Image.id.in_(
                select(m.DatasetItem.image_id).where(
                    m.DatasetItem.dataset_version_id == p["dataset_version_id"]
                )
            )
        )
    if p.get("annotation_status"):
        latest = (
            select(m.Annotation.status)
            .where(m.Annotation.image_id == m.Image.id)
            .order_by(m.Annotation.version.desc())
            .limit(1)
            .scalar_subquery()
        )
        stmt = stmt.where(
            latest.is_(None) if p["annotation_status"] == "none" else latest == p["annotation_status"]
        )
    if p.get("q"):
        stmt = stmt.where(or_(m.Image.filename.contains(p["q"]), m.Image.id.startswith(p["q"])))
    return page(request, db, stmt, m.Image, lambda x: image_json(db, x))


@router.get("/images/{id}")
def image_detail(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("image:read"))
):
    return reply(request, image_json(db, get(db, m.Image, id)))


@router.get("/images/{id}/file")
def image_file(
    id: str,
    request: Request,
    variant: Literal["thumb", "preview", "original"] = "thumb",
    db=Depends(get_db, scope="function"),
    user=Depends(require("image:read")),
):
    image = get(db, m.Image, id)
    if variant == "original" and not has(user, "image:download"):
        raise APIError(403, "无原图下载权限")
    bucket, key = (
        ("bidlsp-raw", image.object_key)
        if variant == "original"
        else ("bidlsp-curated", image.cache_key if variant == "thumb" else image.preview_key)
    )
    audit(db, user, "image.download", image, request, {"variant": variant})
    return RedirectResponse(storage.url(bucket, key), 302, headers={"Cache-Control": "no-store"})


@router.get("/images/{id}/mask")
def image_mask(
    id: str,
    request: Request,
    type: Literal["reference", "approved", "annotation"] = "reference",
    annotation_id: str | None = None,
    db=Depends(get_db, scope="function"),
    user=Depends(require("image:read")),
):
    image = get(db, m.Image, id)
    key = image.mask_object_key
    if type != "reference":
        stmt = select(m.Annotation).where(m.Annotation.image_id == id)
        stmt = (
            stmt.where(m.Annotation.status == "approved")
            if type == "approved"
            else stmt.where(m.Annotation.id == annotation_id)
        )
        annotation = db.scalar(stmt)
        key = annotation.mask_key if annotation else None
    if not key:
        raise APIError(404, "没有对应掩膜")
    return RedirectResponse(storage.url("bidlsp-curated", key), 302, headers={"Cache-Control": "no-store"})


@router.post("/dataset-versions", status_code=201)
def create_version(
    body: s.VersionCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("dataset:write")),
):
    get(db, m.Dataset, body.dataset_id)
    obj = m.DatasetVersion(**body.model_dump(), created_by=user.id)
    db.add(obj)
    db.flush()
    audit(db, user, "dataset.version.create", obj, request)
    return reply(request, version_json(obj), 201)


@router.post("/dataset-versions/{id}/freeze")
def freeze_version(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("dataset:write"))
):
    obj = freeze(db, get(db, m.DatasetVersion, id, lock=True), user, request)
    return reply(request, version_json(obj))


@router.get("/dataset-versions")
def versions(request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    stmt = select(m.DatasetVersion)
    for field in ("dataset_id", "status"):
        if request.query_params.get(field):
            stmt = stmt.where(getattr(m.DatasetVersion, field) == request.query_params[field])
    return page(request, db, stmt, m.DatasetVersion, version_json)


@router.get("/dataset-versions/{id}")
def version_detail(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)
):
    return reply(request, version_json(get(db, m.DatasetVersion, id)))


@router.get("/dataset-versions/{id}/manifest")
def manifest(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("user:manage"))
):
    obj = get(db, m.DatasetVersion, id)
    if not obj.manifest_key:
        raise APIError(409, "版本尚未冻结")
    audit(db, user, "data.export", obj, request)
    return RedirectResponse(
        storage.url("bidlsp-dataset", obj.manifest_key), 302, headers={"Cache-Control": "no-store"}
    )
