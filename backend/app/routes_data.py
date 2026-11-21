import hashlib
import tempfile
from datetime import date
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select

from . import models as m
from . import schemas as s
from .common import APIError, audit, get, page, queue, remember, replay, reply, serialize
from .config import settings
from .data_service import dataset_gap, freeze, validate_archive
from .db import get_db, now, uid
from .notifications import notify
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
        excluded=bool(image.exclude_reason),
        thumbnail_url=storage.url("bidlsp-curated", image.cache_key) if image.cache_key else None,
        preview_url=storage.url("bidlsp-curated", image.preview_key) if image.preview_key else None,
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
    if p.get("unassigned") == "true":
        stmt = stmt.where(m.Image.study_id.is_(None))
    if p.get("exclude") == "true":
        stmt = stmt.where(m.Image.exclude_reason.is_not(None))
    elif p.get("exclude") == "false":
        stmt = stmt.where(m.Image.exclude_reason.is_(None))
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


@router.get("/studies")
def studies(request: Request, db=Depends(get_db, scope="function"), user=Depends(require("image:read"))):
    p = request.query_params
    try:
        number, size = int(p.get("page", 1)), int(p.get("page_size", 20))
        if number < 1 or size < 1 or size > 100:
            raise ValueError()
    except ValueError:
        raise APIError(422, "page >= 1; page_size between 1 and 100") from None
    stmt = select(m.Study, m.Patient).join(m.Patient, m.Patient.id == m.Study.patient_id)
    if p.get("q"):
        like = "%" + p["q"] + "%"
        stmt = stmt.where(or_(m.Study.study_no.like(like), m.Patient.patient_no.like(like)))
    if p.get("status"):
        stmt = stmt.where(m.Study.status == p["status"])
    for field, lower in (("from", True), ("to", False)):
        if p.get(field):
            try:
                stamp = date.fromisoformat(p[field])
            except ValueError:
                raise APIError(422, "日期必须为 YYYY-MM-DD") from None
            stmt = stmt.where(m.Study.study_date >= stamp if lower else m.Study.study_date <= stamp)
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
    rows = db.execute(
        stmt.order_by(m.Study.study_date.desc(), m.Study.created_at.desc())
        .offset((number - 1) * size)
        .limit(size)
    ).all()
    ids = [study.id for study, _ in rows]
    counts = (
        dict(
            db.execute(
                select(m.Image.study_id, func.count())
                .where(m.Image.study_id.in_(ids))
                .group_by(m.Image.study_id)
            ).all()
        )
        if ids
        else {}
    )
    tasks = (
        {t.study_id: t for t in db.scalars(select(m.ScreenTask).where(m.ScreenTask.study_id.in_(ids)))}
        if ids
        else {}
    )
    reports = {}
    for report in (
        db.scalars(select(m.Report).where(m.Report.study_id.in_(ids)).order_by(m.Report.version))
        if ids
        else []
    ):
        reports[report.study_id] = report
    data = []
    for study, patient in rows:
        task, report = tasks.get(study.id), reports.get(study.id)
        data.append(
            {
                **serialize(study),
                "patient_no": patient.patient_no,
                "gender": patient.gender,
                "birth_year": patient.birth_year,
                "image_count": counts.get(study.id, 0),
                "screen_task": {
                    "id": task.id,
                    "status": task.status,
                    "priority": task.priority,
                }
                if task
                else None,
                "report": {"id": report.id, "status": report.status, "version": report.version}
                if report
                else None,
            }
        )
    return reply(request, data, page=number, page_size=size, total=total)


@router.get("/images/{id}")
def image_detail(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("image:read"))
):
    return reply(request, image_json(db, get(db, m.Image, id)))


@router.post("/images/{id}/exclude")
def exclude_image(
    id: str,
    body: s.ImageExclude,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("dataset:write")),
):
    image = get(db, m.Image, id, lock=True)
    reason = (body.exclude_reason or "").strip() or None
    image.exclude_reason = reason
    image.excluded_by = user.id if reason else None
    image.excluded_at = now() if reason else None
    audit(
        db,
        user,
        "image.exclude" if reason else "image.restore",
        image,
        request,
        {"exclude_reason": reason},
    )
    db.flush()
    return reply(request, image_json(db, image))


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
    version = get(db, m.DatasetVersion, id, lock=True)
    if version.status == "draft":
        gap = dataset_gap(db, version)
        if gap["missing_approved_count"] or gap["missing_mask_count"]:
            from fastapi.responses import JSONResponse

            from .common import fingerprint

            audit(db, user, "dataset.gap", version, request, gap)
            notify(
                db,
                [version.created_by],
                "dataset.gap",
                version,
                "数据集冻结存在缺口",
                "请生成补标任务，补齐后重新冻结",
                "/data/datasets",
                version=fingerprint(gap),
            )
            # Return an error response normally so the gap audit and notice commit.
            return JSONResponse(
                {
                    "code": "DATASET_GAP",
                    "message": "存在缺少已通过标注或掩膜的影像",
                    "details": gap,
                    "request_id": request.state.request_id,
                },
                status_code=422,
            )
    obj = freeze(db, version, user, request)
    return reply(request, version_json(obj))


@router.post("/dataset-versions/{id}/archive")
def archive_version(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("dataset:write"))
):
    obj = get(db, m.DatasetVersion, id, lock=True)
    if obj.status != "frozen":
        raise APIError(409, "只能归档已冻结版本")
    obj.status = "archived"
    audit(db, user, "dataset.archive", obj, request)
    db.flush()
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
