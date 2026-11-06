from fastapi import APIRouter, Depends, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import func, or_, select

from . import models as m
from . import schemas as s
from .common import APIError, audit, get, page, reply, serialize, user_ref
from .config import DISCLAIMER
from .db import get_db, now, uid
from .reports import pdf_bytes, render, validate_template
from .routes_annotations import claim, save_annotation
from .routes_data import image_json
from .routes_models import inference_json
from .security import current_user, require
from .storage import storage

router = APIRouter()


def ensure_owner(db, study_id, user):
    task = db.scalar(select(m.ScreenTask).where(m.ScreenTask.study_id == study_id).with_for_update())
    if not task or task.assignee_id != user.id:
        raise APIError(409, "请先领取该检查的筛查任务")
    return task


def result_for_study(db, study_id, result_id=None):
    stmt = (
        select(m.InferenceResult)
        .join(m.InferenceTask, m.InferenceResult.task_id == m.InferenceTask.id)
        .join(m.Image, m.InferenceTask.image_id == m.Image.id)
        .where(m.Image.study_id == study_id, m.InferenceTask.status == "succeeded")
    )
    if result_id:
        stmt = stmt.where(m.InferenceResult.id == result_id)
    obj = db.scalar(stmt.order_by(m.InferenceResult.created_at.desc()))
    if result_id and obj is None:
        raise APIError(422, "推理结果不存在或不属于该检查")
    return obj


def report_json(db, obj):
    return {
        **serialize(obj),
        "author": user_ref(db, obj.author_id),
        "reviewer": user_ref(db, obj.reviewer_id),
        "disclaimer": DISCLAIMER,
        "pdf_url": storage.url("bidlsp-report", obj.pdf_key) if obj.pdf_key else None,
    }


@router.post("/patients", status_code=201)
def patient(
    body: s.PatientCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("screening:manage")),
):
    data = body.model_dump()
    data["patient_no"] = data["patient_no"] or "P" + uid().replace("-", "")[:16]
    obj = m.Patient(**data, created_by=user.id)
    db.add(obj)
    db.flush()
    audit(db, user, "patient.create", obj, request)
    return reply(request, serialize(obj), 201)


@router.get("/patients")
def patients(
    request: Request, db=Depends(get_db, scope="function"), user=Depends(require("screening:manage"))
):
    stmt = select(m.Patient)
    if request.query_params.get("q"):
        stmt = stmt.where(m.Patient.patient_no.contains(request.query_params["q"]))
    return page(request, db, stmt, m.Patient)


@router.post("/studies", status_code=201)
def study(
    body: s.StudyCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("screening:manage")),
):
    get(db, m.Patient, body.patient_id)
    data = body.model_dump(exclude={"image_ids"})
    data["study_no"] = data["study_no"] or "US" + uid().replace("-", "")[:16]
    obj = m.Study(**data, created_by=user.id)
    db.add(obj)
    db.flush()
    for image_id in sorted(set(body.image_ids)):
        image = get(db, m.Image, image_id, lock=True)
        if image.study_id:
            raise APIError(409, "影像已关联检查")
        image.study_id = obj.id
    audit(db, user, "study.created", obj, request, {"study_id": obj.id})
    return reply(request, serialize(obj), 201)


@router.get("/studies/{id}")
def study_detail(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("image:read"))
):
    obj = get(db, m.Study, id)
    images = list(db.scalars(select(m.Image).where(m.Image.study_id == id)))
    ids = [i.id for i in images]
    inference = db.scalar(
        select(m.InferenceTask)
        .where(m.InferenceTask.image_id.in_(ids))
        .order_by(m.InferenceTask.created_at.desc())
    )
    report_ids = list(db.scalars(select(m.Report.id).where(m.Report.study_id == id)))
    task_ids = list(db.scalars(select(m.InferenceTask.id).where(m.InferenceTask.image_id.in_(ids))))
    reviews = list(
        db.scalars(
            select(m.StudyReview).where(m.StudyReview.study_id == id).order_by(m.StudyReview.created_at)
        )
    )
    timeline = db.scalars(
        select(m.AuditLog)
        .where(m.AuditLog.object_id.in_([id] + report_ids + task_ids + [r.id for r in reviews]))
        .order_by(m.AuditLog.created_at)
    )
    return reply(
        request,
        {
            **serialize(obj),
            "patient": serialize(get(db, m.Patient, obj.patient_id)),
            "images": [image_json(db, i) for i in images],
            "latest_inference": inference_json(db, inference) if inference else None,
            "reviews": [serialize(r) for r in reviews],
            "timeline": [
                {"action": a.action, "actor": user_ref(db, a.actor_id), "at": serialize(a)["created_at"]}
                for a in timeline
            ],
        },
    )


@router.post("/screen-tasks", status_code=201)
def screen_task(
    body: s.ScreenCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("screening:manage")),
):
    get(db, m.Study, body.study_id)
    obj = m.ScreenTask(**body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "screen.task.create", obj, request)
    return reply(request, serialize(obj), 201)


@router.get("/screen-tasks")
def screen_tasks(
    request: Request, db=Depends(get_db, scope="function"), user=Depends(require("screening:manage"))
):
    stmt = select(m.ScreenTask)
    p = request.query_params
    if p.get("status"):
        stmt = stmt.where(m.ScreenTask.status == p["status"])
    elif p.get("assignee") != "me" and "admin" not in user.roles:
        stmt = stmt.where(
            or_(
                m.ScreenTask.status == "pending",
                (m.ScreenTask.status == "in_progress") & (m.ScreenTask.assignee_id == user.id),
            )
        )
    if p.get("assignee") == "me":
        stmt = stmt.where(m.ScreenTask.assignee_id == user.id)
    if p.get("priority"):
        if p["priority"] not in ("1", "2", "3", "4", "5"):
            raise APIError(422, "priority 必须为 1–5")
        stmt = stmt.where(m.ScreenTask.priority == int(p["priority"]))
    return page(
        request, db, stmt, m.ScreenTask, lambda x: {**serialize(x), "assignee": user_ref(db, x.assignee_id)}
    )


@router.post("/screen-tasks/{id}/claim")
def screen_claim(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("screening:manage"))
):
    obj = claim(db, m.ScreenTask, id, user)
    get(db, m.Study, obj.study_id).status = "in_progress"
    audit(db, user, "screen.claim", obj, request)
    return reply(request, serialize(obj))


@router.post("/studies/{id}/reviews")
def study_review(
    id: str,
    body: s.StudyDecision,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("screening:manage")),
):
    study = get(db, m.Study, id, lock=True)
    task = ensure_owner(db, id, user)
    if task.status == "done":
        raise APIError(409, "检查已复核完成")
    images = list(db.scalars(select(m.Image).where(m.Image.study_id == id)))
    annotation, result, image = None, None, None
    if body.annotation_id:
        annotation = get(db, m.Annotation, body.annotation_id)
        image = get(db, m.Image, annotation.image_id)
        if image.study_id != id:
            raise APIError(422, "标注不属于该检查")
    if body.image_id:
        image = get(db, m.Image, body.image_id)
        if image.study_id != id:
            raise APIError(422, "影像不属于该检查")
    if body.decision == "modify":
        if not body.mask_rle:
            raise APIError(422, "修改必须提供掩膜")
        if not image:
            if len(images) != 1:
                raise APIError(422, "多影像检查修改必须指定 image_id")
            image = images[0]
        annotation = save_annotation(
            db,
            s.AnnotationCreate(
                image_id=image.id,
                mask_rle=body.mask_rle,
                source="manual",
                is_empty=body.is_empty,
                note=body.comment,
            ),
            user,
            enforce_owner=False,
        )
    elif body.decision == "reject":
        if not (body.comment or "").strip():
            raise APIError(422, "驳回必须填写理由")
    elif annotation is None:
        result = result_for_study(db, id)
        if result is None:
            raise APIError(409, "没有可接受的推理结果或标注")
        image = get(db, m.Image, get(db, m.InferenceTask, result.task_id).image_id)
    obj = m.StudyReview(
        study_id=id,
        image_id=image.id if image else None,
        annotation_id=annotation.id if annotation else None,
        inference_result_id=result.id if result else None,
        reviewer_id=user.id,
        decision=body.decision,
        comment=body.comment,
        follow_up=body.follow_up,
    )
    db.add(obj)
    db.flush()
    if body.decision != "reject":
        task.status, task.finished_at = "done", now()
    audit(db, user, "study.review", obj, request, {"study_id": study.id, "decision": body.decision})
    return reply(
        request, {**serialize(obj), "reviewed_by": user_ref(db, user.id), "reviewed_at": obj.created_at}
    )


@router.get("/report-templates")
def templates(request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    stmt = select(m.ReportTemplate)
    if request.query_params.get("active"):
        if request.query_params["active"] not in ("true", "false"):
            raise APIError(422, "active 必须为 true/false")
        stmt = stmt.where(m.ReportTemplate.active == (request.query_params["active"] == "true"))
    return page(request, db, stmt, m.ReportTemplate)


@router.post("/report-templates", status_code=201)
def template_create(
    body: s.TemplateCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("report:template")),
):
    validate_template(body.body, body.variables)
    obj = m.ReportTemplate(**body.model_dump())
    db.add(obj)
    db.flush()
    audit(db, user, "report.template.create", obj, request)
    return reply(request, serialize(obj), 201)


@router.patch("/report-templates/{id}")
def template_update(
    id: str,
    body: s.TemplatePatch,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("report:template")),
):
    obj = get(db, m.ReportTemplate, id)
    for key, value in body.model_dump(exclude_none=True).items():
        setattr(obj, key, value)
    validate_template(obj.body, obj.variables)
    audit(db, user, "report.template.update", obj, request)
    db.flush()
    return reply(request, serialize(obj))


@router.post("/reports", status_code=201)
def report_create(
    body: s.ReportCreate,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("report:draft")),
):
    study = get(db, m.Study, body.study_id, lock=True)
    task = ensure_owner(db, study.id, user)
    if task.status != "done":
        raise APIError(409, "请先完成医生复核")
    latest = db.scalar(
        select(m.Report).where(m.Report.study_id == study.id).order_by(m.Report.version.desc())
    )
    if latest and latest.status in ("pending_review", "signed"):
        raise APIError(409, "待审或已签发报告不能继续改写")
    template = get(db, m.ReportTemplate, body.template_id)
    if not template.active:
        raise APIError(409, "模板已停用")
    result = result_for_study(db, study.id, body.inference_result_id)
    inference = get(db, m.InferenceTask, result.task_id) if result else None
    model = get(db, m.ModelVersion, inference.model_version_id) if inference else None
    patient = get(db, m.Patient, study.patient_id)
    review = db.scalar(
        select(m.StudyReview)
        .where(m.StudyReview.study_id == study.id)
        .order_by(m.StudyReview.created_at.desc())
    )
    snapshot = {
        "patient_no": patient.patient_no,
        "study_no": study.study_no,
        "study_date": study.study_date.isoformat(),
        "model_version": model.version if model else "",
        "model_version_id": model.id if model else None,
        "weights_sha256": model.weights_sha256 if model else None,
        "params": inference.params if inference else None,
        "lesion_area_ratio": result.lesion_area_ratio if result else "",
        "review_conclusion": review.decision,
        "review_id": review.id,
        "reviewer_id": review.reviewer_id,
        "annotation_id": review.annotation_id,
        "image_ids": list(db.scalars(select(m.Image.id).where(m.Image.study_id == study.id))),
        "dataset_version_ids": list(
            db.scalars(
                select(m.DatasetItem.dataset_version_id)
                .join(m.Image, m.Image.id == m.DatasetItem.image_id)
                .where(m.Image.study_id == study.id)
                .distinct()
            )
        ),
        "template_body": template.body,
        "disclaimer": DISCLAIMER,
    }
    obj = m.Report(
        study_id=study.id,
        inference_result_id=result.id if result else None,
        template_id=template.id,
        content=body.content.model_dump(),
        snapshot=snapshot,
        rendered_html=render(template.body, {**snapshot, **body.content.model_dump()}),
        version=latest.version + 1 if latest else 1,
        author_id=user.id,
    )
    db.add(obj)
    db.flush()
    audit(db, user, "report.save", obj, request)
    return reply(request, report_json(db, obj), 201)


@router.get("/reports/{id}")
def report_detail(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)
):
    return reply(request, report_json(db, get(db, m.Report, id)))


@router.post("/reports/{id}/submit")
def report_submit(
    id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(require("report:draft"))
):
    obj = get(db, m.Report, id, lock=True)
    if obj.author_id != user.id:
        raise APIError(403, "只能提交本人报告")
    newest = db.scalar(select(func.max(m.Report.version)).where(m.Report.study_id == obj.study_id))
    if obj.status != "draft" or obj.version != newest:
        raise APIError(409, "只能提交最新草稿")
    if DISCLAIMER not in obj.rendered_html:
        raise APIError(422, "缺少免责声明")
    obj.status = "pending_review"
    audit(db, user, "report.submit", obj, request)
    db.flush()
    return reply(request, report_json(db, obj))


@router.post("/reports/{id}/sign")
def report_sign(
    id: str,
    body: s.ReportDecision,
    request: Request,
    db=Depends(get_db, scope="function"),
    user=Depends(require("report:sign")),
):
    obj = get(db, m.Report, id, lock=True)
    if obj.status != "pending_review":
        raise APIError(409, "报告不在待签发状态", "REPORT_NOT_SIGNABLE")
    if obj.author_id == user.id and ("admin" not in user.roles or not (body.comment or "").strip()):
        raise APIError(409, "起草人与签发人必须分离；管理员代签须说明原因", "REPORT_NOT_SIGNABLE")
    if body.decision == "reject" and not (body.comment or "").strip():
        raise APIError(422, "驳回必须填写意见")
    if obj.inference_result_id:
        result_for_study(db, obj.study_id, obj.inference_result_id)
    author_name = get(db, m.User, obj.author_id).display_name
    study = get(db, m.Study, obj.study_id)
    obj.reviewer_id, obj.review_comment = user.id, body.comment
    if body.decision == "sign":
        obj.status, obj.signed_at = "signed", now()
        obj.rendered_html = render(
            obj.snapshot["template_body"],
            {
                **obj.snapshot,
                **obj.content,
                "reviewer": user.display_name,
                "signed_at": obj.signed_at.isoformat(),
            },
        )
        data = pdf_bytes(obj, author_name, user.display_name)
        obj.pdf_key = storage.put(
            "bidlsp-report", f"reports/{obj.id}/v{obj.version}.pdf", data, "application/pdf"
        )
        study.status = "reported"
    else:
        obj.status = "draft"
    audit(
        db,
        user,
        "report.sign" if body.decision == "sign" else "report.reject",
        obj,
        request,
        {"comment": body.comment, "admin_override": obj.author_id == user.id},
    )
    db.flush()
    return reply(request, report_json(db, obj))


@router.get("/reports/{id}/pdf")
def report_pdf(id: str, request: Request, db=Depends(get_db, scope="function"), user=Depends(current_user)):
    obj = get(db, m.Report, id)
    key = obj.pdf_key
    if not key:
        data = pdf_bytes(obj, get(db, m.User, obj.author_id).display_name, "")
        key = storage.put("bidlsp-report", f"previews/{obj.id}/{uid()}.pdf", data, "application/pdf")
    audit(db, user, "report.export", obj, request)
    return RedirectResponse(storage.url("bidlsp-report", key), 302, headers={"Cache-Control": "no-store"})
