"""Member A return-path integration tests; inference uses an explicit test double."""

import json
from datetime import timedelta

import pytest
from app import models as m
from app import worker
from app.config import ROOT, settings
from app.db import SessionLocal, engine, now
from app.notifications import notify
from app.security import token
from app.task_lifecycle import recover_overdue
from sqlalchemy import func, select, text
from sqlalchemy.exc import DatabaseError
from test_platform import post


def rows(client, path, header):
    response = client.get("/api/v1" + path, headers=header)
    assert response.status_code == 200, response.text
    return response.json()["data"]


def prepare_study(client, headers, images):
    h = headers["screener"]
    patient = post(client, "/patients", h, {"gender": "F"}, 201)
    study = post(
        client,
        "/studies",
        h,
        {"patient_id": patient["id"], "study_date": "2026-11-21", "image_ids": [images[0]["id"]]},
        201,
    )
    task = post(client, "/screen-tasks", h, {"study_id": study["id"]}, 201)
    post(client, f"/screen-tasks/{task['id']}/claim", h)
    return study, task


def finish_manual(client, headers, study):
    return post(
        client,
        f"/studies/{study['id']}/reviews",
        headers["screener"],
        {"decision": "modify", "mask_rle": {"size": [12, 16], "counts": [0, 192]}, "comment": "人工复核"},
    )


def prepare_report(client, headers, images):
    study, task = prepare_study(client, headers, images)
    finish_manual(client, headers, study)
    template = rows(client, "/report-templates", headers["admin"])[0]
    report = post(
        client,
        "/reports",
        headers["screener"],
        {
            "study_id": study["id"],
            "template_id": template["id"],
            "content": {"findings": "原始影像所见", "impression": "待复核", "recommendation": "科研使用"},
        },
        201,
    )
    return study, task, report


def test_notification_isolation_dedupe_read_and_savepoint(client, headers, imported):
    dataset_id, _ = imported
    with SessionLocal() as db:
        dataset = db.get(m.Dataset, dataset_id)
        users = {u.username: u for u in db.scalars(select(m.User))}
        for _ in range(2):
            notify(db, [users["annotator"].id], "dataset.gap", dataset, "缺口", version="v1")
        # An invalid recipient violates the FK inside a savepoint, not the main transaction.
        notify(db, ["00000000-0000-0000-0000-000000000000"], "dataset.gap", dataset, "缺口", version="bad")
        dataset.description = "business transaction survived"
        db.commit()
    notices = rows(client, "/notifications", headers["annotator"])
    assert len(notices) == 1
    assert rows(client, "/notifications/unread-count", headers["annotator"])["count"] == 1
    assert rows(client, "/notifications", headers["screener"]) == []
    assert (
        client.post(f"/api/v1/notifications/{notices[0]['id']}/read", headers=headers["admin"]).status_code
        == 404
    )
    first = post(client, f"/notifications/{notices[0]['id']}/read", headers["annotator"])
    second = post(client, f"/notifications/{notices[0]['id']}/read", headers["annotator"])
    assert first["read_at"] == second["read_at"]
    assert post(client, "/notifications/read-all", headers["annotator"])["updated"] == 0
    with SessionLocal() as db:
        assert db.get(m.Dataset, dataset_id).description == "business transaction survived"
        assert (
            db.scalar(
                select(func.count()).select_from(m.AuditLog).where(m.AuditLog.action == "notification.send")
            )
            == 1
        )
    with engine.connect() as conn:
        with pytest.raises(DatabaseError):
            conn.execute(text("UPDATE notification SET title='tampered'"))
        conn.rollback()


def test_gap_batch_repair_then_freeze(client, headers, imported):
    dataset_id, images = imported
    missing_ids = [i["id"] for i in images[:3]]
    with SessionLocal() as db:
        for a in db.scalars(select(m.Annotation).where(m.Annotation.image_id.in_(missing_ids))):
            a.status = "rejected"
        db.commit()
    h = headers["data_engineer"]
    version = post(client, "/dataset-versions", h, {"dataset_id": dataset_id, "version": "gap"}, 201)
    url = f"/api/v1/dataset-versions/{version['id']}/freeze"
    for _ in range(2):
        gap = client.post(url, headers=h)
        assert gap.status_code == 422
        assert gap.json()["code"] == "DATASET_GAP"
        assert gap.json()["details"]["missing_approved_count"] == 3
        assert {i["image_id"] for i in gap.json()["details"]["missing_approved_sample"]} == set(missing_ids)
    assert len(rows(client, "/notifications", h)) == 1
    payload = {"dataset_version_id": version["id"]}
    batch = post(client, "/annotation-tasks/batch", {**h, "Idempotency-Key": "gap"}, payload, 201)
    assert (batch["created"], batch["existing"], batch["skipped"]) == (3, 0, 18)
    replay = post(client, "/annotation-tasks/batch", {**h, "Idempotency-Key": "gap"}, payload, 201)
    assert replay == batch
    again = post(client, "/annotation-tasks/batch", h, payload, 201)
    assert (again["created"], again["existing"]) == (0, 3)
    for task_id in batch["task_ids"]:
        task = post(client, f"/annotation-tasks/{task_id}/claim", headers["annotator"])
        annotation = post(
            client,
            "/annotations",
            headers["annotator"],
            {
                "image_id": task["image_id"],
                "source": "manual",
                "mask_rle": {"size": [12, 16], "counts": [0, 192]},
            },
            201,
        )
        post(client, f"/annotations/{annotation['id']}/submit", headers["annotator"])
        post(client, f"/annotations/{annotation['id']}/reviews", headers["reviewer"], {"decision": "approve"})
    frozen = client.post(url, headers=h)
    assert frozen.status_code == 200, frozen.text
    assert frozen.json()["data"]["counts"] == {"train": 15, "val": 3, "test": 3}
    assert client.post(url, headers=h).status_code == 409


def test_missing_mask_is_a_gap_and_generates_repair_task(client, headers, imported):
    dataset_id, images = imported
    with SessionLocal() as db:
        annotation = db.scalar(select(m.Annotation).where(m.Annotation.image_id == images[0]["id"]))
        annotation.mask_key = "missing/mask.png"
        db.commit()
    h = headers["admin"]
    version = post(client, "/dataset-versions", h, {"dataset_id": dataset_id, "version": "mask-gap"}, 201)
    response = client.post(f"/api/v1/dataset-versions/{version['id']}/freeze", headers=h)
    assert response.status_code == 422
    assert response.json()["details"]["missing_mask_count"] == 1
    batch = post(client, "/annotation-tasks/batch", h, {"dataset_version_id": version["id"]}, 201)
    assert batch["created"] == 1


def test_annotation_rejection_notifies_author_and_live_todos(client, headers, imported):
    _, images = imported
    batch = post(
        client,
        "/annotation-tasks/batch",
        headers["admin"],
        {"image_ids": [images[0]["id"]], "only_missing_approved": False},
        201,
    )
    task = post(client, f"/annotation-tasks/{batch['task_ids'][0]}/claim", headers["annotator"])
    annotation = post(
        client,
        "/annotations",
        headers["annotator"],
        {
            "image_id": task["image_id"],
            "source": "preannot",
            "mask_rle": {"size": [12, 16], "counts": [0, 192]},
        },
        201,
    )
    post(client, f"/annotations/{annotation['id']}/submit", headers["annotator"])
    assert rows(client, "/todos", headers["reviewer"])["items"][0]["id"] == annotation["id"]
    post(
        client,
        f"/annotations/{annotation['id']}/reviews",
        headers["reviewer"],
        {"decision": "reject", "comment": "重修边界"},
    )
    notice = rows(client, "/notifications", headers["annotator"])[0]
    assert notice["body"] == "重修边界" and notice["link"].endswith(task["image_id"])
    assert rows(client, "/todos", headers["reviewer"])["total"] == 0
    quality = rows(client, "/stats/quality", headers["admin"])
    assert quality["annotation_rejection"]["rate"] == 1


def test_report_rejected_revision_void_and_immutable_evidence(client, headers, imported):
    study, _, original = prepare_report(client, headers, imported[1])
    h, reviewer, admin = headers["screener"], headers["reviewer"], headers["admin"]
    post(client, f"/reports/{original['id']}/submit", h)
    assert any(i["id"] == original["id"] for i in rows(client, "/todos", reviewer)["items"])
    rejected = post(
        client, f"/reports/{original['id']}/sign", reviewer, {"decision": "reject", "comment": "补充描述"}
    )
    assert rejected["status"] == "rejected" and rejected["rejected_at"] and rejected["pdf_key"]
    rejected_pdf = client.get(rejected["pdf_url"]).content
    assert client.post(f"/api/v1/reports/{original['id']}/submit", headers=h).status_code == 409
    revision = post(
        client,
        f"/reports/{original['id']}/revisions",
        h,
        {"content": {"findings": "已补充", "impression": "已复核", "recommendation": "科研使用"}},
        201,
    )
    assert revision["version"] == 2 and revision["previous_report_id"] == original["id"]
    assert client.post(f"/api/v1/reports/{original['id']}/revisions", headers=h, json={}).status_code == 409
    post(client, f"/reports/{revision['id']}/submit", h)
    signed = post(client, f"/reports/{revision['id']}/sign", reviewer, {"decision": "sign"})
    signed_pdf = client.get(signed["pdf_url"]).content
    assert (
        client.post(
            f"/api/v1/reports/{revision['id']}/void", headers=reviewer, json={"reason": "更正"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/reports/{revision['id']}/void", headers=admin, json={"reason": "  "}
        ).status_code
        == 422
    )
    voided = post(client, f"/reports/{revision['id']}/void", admin, {"reason": "检查信息需更正"})
    assert voided["status"] == "voided" and voided["pdf_key"] == signed["pdf_key"]
    assert client.get(voided["pdf_url"]).content == signed_pdf
    assert rows(client, f"/studies/{study['id']}", h)["status"] == "reopened"
    corrected = post(client, f"/reports/{revision['id']}/revisions", h, {}, 201)
    post(client, f"/reports/{corrected['id']}/submit", h)
    assert (
        post(client, f"/reports/{corrected['id']}/sign", reviewer, {"decision": "sign"})["status"] == "signed"
    )
    assert rows(client, f"/studies/{study['id']}", h)["status"] == "reported"
    assert client.get(rows(client, f"/reports/{original['id']}", h)["pdf_url"]).content == rejected_pdf
    for report_id in (original["id"], revision["id"], corrected["id"]):
        with engine.connect() as conn:
            with pytest.raises(DatabaseError):
                conn.execute(text("UPDATE report SET content='{}' WHERE id=:id"), {"id": report_id})
            conn.rollback()
            with pytest.raises(DatabaseError):
                conn.execute(text("DELETE FROM report WHERE id=:id"), {"id": report_id})
            conn.rollback()
    notices = rows(client, "/notifications", h)
    assert {n["type"] for n in notices} >= {"report.rejected", "report.voided"}


def test_even_admin_cannot_sign_own_report(client, headers, imported):
    _, _, report = prepare_report(client, headers, imported[1])
    with SessionLocal() as db:
        admin = db.scalar(select(m.User).where(m.User.username == "admin"))
        db.get(m.Report, report["id"]).author_id = admin.id
        db.commit()
    post(client, f"/reports/{report['id']}/submit", headers["admin"])
    response = client.post(
        f"/api/v1/reports/{report['id']}/sign",
        headers=headers["admin"],
        json={"decision": "sign", "comment": "不能自签"},
    )
    assert response.status_code == 409


@pytest.mark.parametrize("follow_up", ["manual", "transfer"])
def test_screen_return_reclaim_and_finish(client, headers, imported, follow_up):
    study, task = prepare_study(client, headers, imported[1])
    h = headers["screener"]
    url = f"/studies/{study['id']}/reviews"
    rejected = post(client, url, h, {"decision": "reject", "comment": "需要重做", "follow_up": follow_up})
    assert rejected["follow_up"] == follow_up
    assert rows(client, f"/studies/{study['id']}", h)["status"] == "returned"
    assert rows(client, "/screen-tasks?status=returned", h)[0]["return_reason"] == "需要重做"
    assert client.post("/api/v1" + url, headers=h, json={"decision": "accept"}).status_code == 409
    if follow_up == "transfer":
        assert client.post(f"/api/v1/screen-tasks/{task['id']}/claim", headers=h).status_code == 409
        user_id = rows(client, "/auth/me", h)["id"]
        post(client, f"/screen-tasks/{task['id']}/reassign", headers["admin"], {"assignee_id": user_id})
    else:
        post(client, f"/screen-tasks/{task['id']}/claim", h)
        assert client.post("/api/v1" + url, headers=h, json={"decision": "accept"}).status_code == 422
    finish_manual(client, headers, study)
    detail = rows(client, f"/studies/{study['id']}", h)
    assert detail["status"] == "reviewed"
    assert any(
        a["action"] == "screen.return" and a["detail"]["follow_up"] == follow_up for a in detail["timeline"]
    )
    with SessionLocal() as db:
        assert (
            db.scalar(
                select(func.count()).select_from(m.ScreenTask).where(m.ScreenTask.study_id == study["id"])
            )
            == 1
        )


def test_screen_reinfer_requires_new_success_and_retry_preserves_history(
    client, headers, imported, monkeypatch
):
    study, task = prepare_study(client, headers, imported[1])
    with SessionLocal() as db:
        model = m.Model(name="transunet")
        db.add(model)
        db.flush()
        config = json.loads((ROOT / "algo/models/registry.json").read_text())["models"][0]["config"]
        user = db.scalar(select(m.User).where(m.User.username == "admin"))
        db.add(
            m.ModelVersion(
                model_id=model.id,
                version="test",
                weights_key="fake.pth",
                weights_sha256="0" * 64,
                config=config,
                status="active",
                created_by=user.id,
            )
        )
        db.commit()
    h = headers["screener"]
    post(
        client,
        f"/studies/{study['id']}/reviews",
        h,
        {"decision": "reject", "follow_up": "re_infer", "comment": "重跑"},
    )
    first = post(client, f"/screen-tasks/{task['id']}/claim", h, status=202)
    old_id = first["retry_task_ids"][0]
    assert client.post(f"/api/v1/screen-tasks/{task['id']}/claim", headers=h).status_code == 409

    def fail(db, task):
        raise ValueError("intentional inference failure")

    monkeypatch.setattr(worker, "run_prediction", fail)
    worker.drain_eager()
    assert any(n["type"] == "task.failed" for n in rows(client, "/notifications", h))
    second = post(client, f"/screen-tasks/{task['id']}/claim", h, status=202)
    new_id = second["retry_task_ids"][0]
    assert new_id != old_id

    def predict(db, inference):
        import numpy as np
        from conftest import png_bytes

        path = settings.work_dir / "test-result.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes(np.ones((12, 16), dtype="uint8") * 255))
        return {
            "result": {
                "mask_rle": {"size": [12, 16], "counts": [0, 192]},
                "prob_mean": 1.0,
                "lesion_area_ratio": 1.0,
                "quality_flags": [],
                "elapsed_ms": 1,
            },
            "artifacts": {"mask": str(path)},
        }

    monkeypatch.setattr(worker, "run_prediction", predict)
    worker.drain_eager()
    post(client, f"/screen-tasks/{task['id']}/claim", h)
    post(client, f"/studies/{study['id']}/reviews", h, {"decision": "accept"})
    assert rows(client, f"/inference-tasks/{old_id}", h)["status"] == "failed"
    assert not any(i["id"] == old_id for i in rows(client, "/todos", h)["items"])
    assert rows(client, f"/studies/{study['id']}", h)["status"] == "reviewed"


def test_sla_warn_once_then_release_and_reclaim(client, headers, imported):
    _, task = prepare_study(client, headers, imported[1])
    with SessionLocal() as db:
        obj = db.get(m.ScreenTask, task["id"])
        obj.claimed_at = now() - timedelta(hours=settings.screening_sla_hours + 1)
        recover_overdue(db)
        recover_overdue(db)
        db.commit()
    notices = rows(client, "/notifications", headers["screener"])
    assert sum(n["type"] == "task.overdue" for n in notices) == 1
    assert rows(client, "/stats/quality", headers["admin"])["overdue_tasks"] == 1
    with SessionLocal() as db:
        db.get(m.ScreenTask, task["id"]).overdue_at = now() - timedelta(
            hours=settings.task_release_grace_hours + 1
        )
        recover_overdue(db)
        db.commit()
    assert post(client, f"/screen-tasks/{task['id']}/claim", headers["admin"])["status"] == "in_progress"


def test_disable_account_releases_single_task_and_revokes_token(client, headers, imported):
    _, task = prepare_study(client, headers, imported[1])
    user_id = rows(client, "/auth/me", headers["screener"])["id"]
    response = client.patch(f"/api/v1/users/{user_id}", headers=headers["admin"], json={"status": "disabled"})
    assert response.status_code == 200
    assert client.get("/api/v1/auth/me", headers=headers["screener"]).status_code == 401
    assert post(client, f"/screen-tasks/{task['id']}/claim", headers["admin"])["status"] == "in_progress"


@pytest.mark.parametrize("reason", ["disabled", "timeout"])
def test_dual_release_preserves_submitted_contribution(client, headers, imported, reason):
    image = imported[1][0]
    with SessionLocal() as db:
        extra = m.User(username="extra", password_hash="unused", display_name="extra", roles=["annotator"])
        db.add(extra)
        db.flush()
        extra_header = {"Authorization": "Bearer " + token(extra)}
        extra_id = extra.id
        db.commit()
    batch = post(
        client,
        "/annotation-tasks/batch",
        headers["admin"],
        {"image_ids": [image["id"]], "required_annotators": 2, "only_missing_approved": False},
        201,
    )
    task_id = batch["task_ids"][0]
    post(client, f"/annotation-tasks/{task_id}/claim", headers["annotator"])
    post(client, f"/annotation-tasks/{task_id}/join", extra_header)
    annotation = post(
        client,
        "/annotations",
        headers["annotator"],
        {"image_id": image["id"], "source": "manual", "mask_rle": {"size": [12, 16], "counts": [0, 192]}},
        201,
    )
    post(client, f"/annotations/{annotation['id']}/submit", headers["annotator"])
    if reason == "disabled":
        assert (
            client.patch(
                f"/api/v1/users/{extra_id}", headers=headers["admin"], json={"status": "disabled"}
            ).status_code
            == 200
        )
    else:
        with SessionLocal() as db:
            task = db.get(m.AnnotationTask, task_id)
            task.claimed_at = now() - timedelta(hours=100)
            task.overdue_at = now() - timedelta(hours=100)
            recover_overdue(db)
            db.commit()
    with SessionLocal() as db:
        assert db.get(m.Annotation, annotation["id"]).status == "pending"
        assignments = list(
            db.scalars(select(m.AnnotationAssignment).where(m.AnnotationAssignment.task_id == task_id))
        )
        assert len(assignments) == 1 and assignments[0].status == "submitted"
    post(client, f"/annotation-tasks/{task_id}/join", headers["admin"])
    second = post(
        client,
        "/annotations",
        headers["admin"],
        {"image_id": image["id"], "source": "manual", "mask_rle": {"size": [12, 16], "counts": [0, 192]}},
        201,
    )
    post(client, f"/annotations/{second['id']}/submit", headers["admin"])
    with SessionLocal() as db:
        assert db.get(m.AnnotationTask, task_id).status == "approved"


def test_upgrade_preserves_existing_signed_report(client, headers, imported):
    from alembic import command
    from alembic.config import Config

    _, _, report = prepare_report(client, headers, imported[1])
    post(client, f"/reports/{report['id']}/submit", headers["screener"])
    signed = post(client, f"/reports/{report['id']}/sign", headers["reviewer"], {"decision": "sign"})
    pdf = client.get(signed["pdf_url"]).content
    config = Config(str(ROOT / "backend/alembic.ini"))
    command.downgrade(config, "0005")
    command.upgrade(config, "head")
    restored = rows(client, f"/reports/{report['id']}", headers["admin"])
    for field in ("content", "snapshot", "signed_at", "pdf_key", "reviewer_id", "status"):
        assert restored[field] == signed[field]
    assert client.get(restored["pdf_url"]).content == pdf
    with engine.connect() as conn:
        with pytest.raises(DatabaseError):
            conn.execute(
                text(
                    "UPDATE report SET status='voided', voided_by=author_id, voided_at=CURRENT_TIMESTAMP, void_reason='bad', content='{}' WHERE id=:id"
                ),
                {"id": report["id"]},
            )
        conn.rollback()
    voided = post(client, f"/reports/{report['id']}/void", headers["admin"], {"reason": "迁移后正常更正"})
    assert voided["pdf_key"] == restored["pdf_key"]


def test_disabled_author_rejection_releases_work(client, headers, imported):
    image_id = imported[1][0]["id"]
    batch = post(
        client,
        "/annotation-tasks/batch",
        headers["admin"],
        {"image_ids": [image_id], "only_missing_approved": False},
        201,
    )
    task_id = batch["task_ids"][0]
    post(client, f"/annotation-tasks/{task_id}/claim", headers["annotator"])
    annotation = post(
        client,
        "/annotations",
        headers["annotator"],
        {"image_id": image_id, "source": "manual", "mask_rle": {"size": [12, 16], "counts": [0, 192]}},
        201,
    )
    post(client, f"/annotations/{annotation['id']}/submit", headers["annotator"])
    user_id = rows(client, "/auth/me", headers["annotator"])["id"]
    assert (
        client.patch(
            f"/api/v1/users/{user_id}", headers=headers["admin"], json={"status": "disabled"}
        ).status_code
        == 200
    )
    post(
        client,
        f"/annotations/{annotation['id']}/reviews",
        headers["reviewer"],
        {"decision": "reject", "comment": "原作者已离场"},
    )
    assert post(client, f"/annotation-tasks/{task_id}/claim", headers["admin"])["status"] == "in_progress"
