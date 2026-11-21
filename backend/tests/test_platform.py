import io
import json
import re
import zipfile

import pytest
from app import models as m
from app.config import DISCLAIMER, ROOT, settings
from app.db import SessionLocal, engine
from app.main import app
from app.storage import storage
from app.worker import drain_eager
from conftest import archive_bytes
from pypdf import PdfReader
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError


def post(client, path, headers, payload=None, status=200):
    response = client.post("/api/v1" + path, headers=headers, json=payload)
    assert response.status_code == status, response.text
    return response.json()["data"] if response.content else None


def test_openapi_matches_contract_endpoints():
    contract = (ROOT / "接口规范.md").read_text(encoding="utf-8")
    expected = re.findall(r"\| \d{3} \| (GET|POST|PATCH) \| `([^`]+)`", contract)
    actual = app.openapi()["paths"]
    assert len(expected) == 85
    for method, path in expected:
        assert method.lower() in actual["/api/v1" + path], path
    assert len(
        [(p, v) for p, methods in actual.items() for v in methods if v in {"get", "post", "patch"}]
    ) == len(expected)


def test_auth_rbac_logout_password_and_last_admin(client, headers):
    assert client.get("/api/v1/images").status_code == 401
    assert client.get("/api/v1/users", headers=headers["screener"]).status_code == 403
    assert (
        client.post("/api/v1/datasets", headers=headers["annotator"], json={"name": "bad"}).status_code == 403
    )
    assert (
        client.post(
            "/api/v1/patients", headers=headers["screener"], json={"gender": "F", "name": "private"}
        ).status_code
        == 422
    )
    login = post(client, "/auth/login", {}, {"username": "admin", "password": "DemoPassword!123"})
    assert login["expires_in"] == 28800
    h = {"Authorization": "Bearer " + login["access_token"]}
    id = login["user"]["id"]
    assert "password_hash" not in login["user"]
    assert client.patch("/api/v1/users/" + id, headers=h, json={"roles": ["screener"]}).status_code == 409
    post(client, "/auth/logout", h, status=204)
    assert client.get("/api/v1/auth/me", headers=h).status_code == 401
    post(
        client,
        "/auth/password",
        headers["screener"],
        {"old_password": "DemoPassword!123", "new_password": "NewPassword!123"},
        204,
    )
    assert client.get("/api/v1/auth/me", headers=headers["screener"]).status_code == 401


def test_registration_requires_admin_activation(client, headers):
    payload = {"username": "newdoctor", "display_name": "新医生", "password": "Register!123"}
    created = post(client, "/auth/register", {}, payload, 201)
    assert created["status"] == "disabled"
    login = {"username": "newdoctor", "password": "Register!123"}
    assert client.post("/api/v1/auth/login", json=login).status_code == 401
    assert client.post("/api/v1/auth/register", json=payload).status_code == 409
    assert (
        client.patch(
            "/api/v1/users/" + created["id"], headers=headers["admin"], json={"status": "active"}
        ).status_code
        == 200
    )
    approved = client.post("/api/v1/auth/login", json=login)
    assert approved.status_code == 200
    assert approved.json()["data"]["user"]["roles"] == ["screener"]


def test_rate_limits_validation_and_health(client):
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/login", json={"username": "unknown", "password": "invalid-password"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"username": "unknown", "password": "invalid-password"}
        ).status_code
        == 429
    )
    assert client.get("/api/v1/healthz").json()["status"] == "ok"
    assert client.get("/api/v1/readyz").status_code == 200


def test_import_idempotency_dedupe_zip_safety_and_permissions(client, headers, imported):
    dataset_id, images = imported
    h = {**headers["admin"], "Idempotency-Key": "repeat-import"}
    path = f"/api/v1/datasets/{dataset_id}/imports"
    data = archive_bytes()
    first = client.post(path, headers=h, files={"file": ("busi.zip", data, "application/zip")})
    second = client.post(path, headers=h, files={"file": ("busi.zip", data, "application/zip")})
    assert first.status_code == second.status_code == 202
    assert second.headers["Idempotent-Replay"] == "true"
    assert first.json()["data"] == second.json()["data"]
    conflict = client.post(path, headers=h, files={"file": ("busi.zip", archive_bytes(6), "application/zip")})
    assert conflict.status_code == 409
    drain_eager()
    job = client.get("/api/v1/imports/" + first.json()["data"]["job_id"], headers=h).json()["data"]
    assert job["success"] == 0 and job["duplicate"] == 21
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as archive:
        archive.writestr("../escape.png", b"bad")
    assert (
        client.post(
            path, headers=headers["admin"], files={"file": ("evil.zip", evil.getvalue(), "application/zip")}
        ).status_code
        == 422
    )
    image = images[0]
    assert (
        client.get(
            f"/api/v1/images/{image['id']}/file?variant=original",
            headers=headers["screener"],
            follow_redirects=False,
        ).status_code
        == 403
    )
    download = client.get(
        f"/api/v1/images/{image['id']}/file", headers=headers["screener"], follow_redirects=False
    )
    assert download.status_code == 302
    assert client.get(download.headers["location"]).content.startswith(b"\x89PNG")
    signature = download.headers["location"].rsplit("/", 1)[1]
    forged = signature[:-5] + "abcde"
    assert client.get("/api/v1/files/" + forged).status_code == 403
    assert client.get("/api/v1/images?sort=password_hash", headers=h).status_code == 422


def test_freeze_manifest_and_database_immutability(client, headers, imported):
    dataset_id, images = imported
    version = post(
        client,
        "/dataset-versions",
        headers["data_engineer"],
        {"dataset_id": dataset_id, "version": "v1"},
        201,
    )
    frozen = post(client, f"/dataset-versions/{version['id']}/freeze", headers["data_engineer"])
    assert frozen["counts"] == {"train": 15, "val": 3, "test": 3}
    assert (
        client.post(f"/api/v1/dataset-versions/{version['id']}/freeze", headers=headers["admin"]).status_code
        == 409
    )
    assert (
        client.get(
            f"/api/v1/dataset-versions/{version['id']}/manifest",
            headers=headers["annotator"],
            follow_redirects=False,
        ).status_code
        == 403
    )
    download = client.get(f"/api/v1/dataset-versions/{version['id']}/manifest", headers=headers["admin"])
    manifest = download.json()
    assert len({i["image_id"] for i in manifest["items"]}) == 21
    assert all(i["annotation_version"] == 1 for i in manifest["items"])
    with engine.connect() as conn:
        with pytest.raises(DatabaseError):
            conn.execute(
                text("UPDATE dataset_version SET version='changed' WHERE id=:id"), {"id": version["id"]}
            )
        conn.rollback()
        with pytest.raises(DatabaseError):
            conn.execute(text("DELETE FROM audit_log"))
        conn.rollback()
    with SessionLocal() as db:
        frozen_row = db.get(m.DatasetVersion, version["id"])
        frozen_row.status = "archived"
        db.commit()
    with engine.connect() as conn:
        with pytest.raises(DatabaseError):
            conn.execute(text("DELETE FROM dataset_item WHERE dataset_version_id=:id"), {"id": version["id"]})
        conn.rollback()


def test_request_size_limit(client, headers, monkeypatch):
    monkeypatch.setattr(settings, "max_upload_mb", 0)
    response = client.post("/api/v1/datasets", headers=headers["admin"], json={"name": "too-large"})
    assert response.status_code == 413
    assert response.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_annotation_claim_versions_rejection_and_unique_approval(client, headers, imported):
    _, images = imported
    image = next(i for i in images if i["class_label"] == "benign")
    task = post(client, "/annotation-tasks", headers["admin"], {"image_ids": [image["id"]]}, 201)["task_ids"][
        0
    ]
    post(client, f"/annotation-tasks/{task}/claim", headers["annotator"])
    assert client.post(f"/api/v1/annotation-tasks/{task}/claim", headers=headers["admin"]).status_code == 409
    payload = {
        "image_id": image["id"],
        "mask_rle": {"size": [12, 16], "counts": [0, 192]},
        "source": "manual",
    }
    assert client.post("/api/v1/annotations", headers=headers["admin"], json=payload).status_code == 409
    annotation = post(client, "/annotations", headers["annotator"], payload, 201)
    assert annotation["version"] == 2
    post(client, f"/annotations/{annotation['id']}/submit", headers["annotator"])
    assert client.post("/api/v1/annotations", headers=headers["annotator"], json=payload).status_code == 409
    assert (
        client.post(
            f"/api/v1/annotations/{annotation['id']}/reviews",
            headers=headers["reviewer"],
            json={"decision": "reject"},
        ).status_code
        == 422
    )
    rejected = post(
        client,
        f"/annotations/{annotation['id']}/reviews",
        headers["reviewer"],
        {"decision": "reject", "comment": "重新修边"},
    )
    assert rejected["status"] == "draft"
    post(client, f"/annotations/{annotation['id']}/submit", headers["annotator"])
    approved = post(
        client, f"/annotations/{annotation['id']}/reviews", headers["reviewer"], {"decision": "approve"}
    )
    assert approved["status"] == "approved"
    with SessionLocal() as db:
        assert (
            len(
                list(
                    db.scalars(
                        select(m.Annotation).where(
                            m.Annotation.image_id == image["id"], m.Annotation.status == "approved"
                        )
                    )
                )
            )
            == 1
        )


def test_inference_screen_report_full_flow(client, headers, imported, monkeypatch):
    import numpy as np
    from app import worker
    from conftest import png_bytes

    _, images = imported
    image = next(i for i in images if i["class_label"] == "benign")
    h = headers["admin"]
    registry = json.loads((ROOT / "algo/models/registry.json").read_text())["models"][0]
    model = post(client, "/models", h, {"name": "transunet"}, 201)
    storage.put("bidlsp-model", "test/weights.pth", b"test-weight")
    import hashlib

    payload = {
        "version": "test",
        "weights_key": "test/weights.pth",
        "weights_sha256": hashlib.sha256(b"test-weight").hexdigest(),
        "config": registry["config"],
        "metrics": registry["metrics"],
    }
    assert (
        client.post(
            f"/api/v1/models/{model['id']}/versions", headers=h, json={**payload, "weights_sha256": "0" * 64}
        ).status_code
        == 422
    )
    version = post(client, f"/models/{model['id']}/versions", h, payload, 201)
    post(client, f"/model-versions/{version['id']}/activate", h)
    listed = client.get("/api/v1/models", headers=h).json()["data"]
    assert any(item["id"] == version["id"] for item in listed[0]["versions"])
    assert listed[0]["active_version"]["id"] == version["id"]

    def fake_prediction(db, task):
        path = settings.work_dir / task.id / "mask.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes(np.ones((12, 16), dtype="uint8") * 255))
        return {
            "result": {
                "mask_rle": {"size": [12, 16], "counts": [0, 192]},
                "prob_mean": 0.8,
                "lesion_area_ratio": 1.0,
                "quality_flags": ["AREA_TOO_LARGE"],
                "elapsed_ms": 20,
            },
            "artifacts": {"mask": str(path), "mask_raw": str(path), "overlay": str(path)},
        }

    monkeypatch.setattr(worker, "run_prediction", fake_prediction)
    patient = post(client, "/patients", headers["screener"], {"gender": "F", "birth_year": 1980}, 201)
    study = post(
        client,
        "/studies",
        headers["screener"],
        {"patient_id": patient["id"], "study_date": "2026-11-02", "image_ids": [image["id"]]},
        201,
    )
    task = post(client, "/screen-tasks", headers["screener"], {"study_id": study["id"]}, 201)
    post(client, f"/screen-tasks/{task['id']}/claim", headers["screener"])
    inf = post(
        client,
        "/inference-tasks",
        {**headers["screener"], "Idempotency-Key": "prediction"},
        {"image_id": image["id"]},
        202,
    )
    drain_eager()
    result = client.get("/api/v1/inference-tasks/" + inf["task_id"], headers=h).json()["data"]
    assert result["status"] == "succeeded", result
    assert result["result"]["mask_url"].startswith("http://testserver/")
    post(client, f"/studies/{study['id']}/reviews", headers["screener"], {"decision": "accept"})
    template = client.get("/api/v1/report-templates", headers=h).json()["data"][0]
    report = post(
        client,
        "/reports",
        headers["screener"],
        {
            "study_id": study["id"],
            "template_id": template["id"],
            "inference_result_id": result["result"]["id"],
            "content": {
                "findings": "科研样例：影像可见低回声区。",
                "impression": "已复核模型掩膜，仅供研究参考。",
                "recommendation": "建议结合其他检查，由专业医师评估。",
            },
        },
        201,
    )
    preview = client.get(f"/api/v1/reports/{report['id']}/pdf", headers=h)
    assert "未签发" in "".join(p.extract_text() for p in PdfReader(io.BytesIO(preview.content)).pages)
    post(client, f"/reports/{report['id']}/submit", headers["screener"])
    signed = post(
        client,
        f"/reports/{report['id']}/sign",
        headers["reviewer"],
        {"decision": "sign", "comment": "已核对科研样例"},
    )
    assert signed["status"] == "signed"
    assert (
        client.post(
            f"/api/v1/reports/{report['id']}/sign", headers=headers["reviewer"], json={"decision": "sign"}
        ).status_code
        == 409
    )
    pdf = client.get(f"/api/v1/reports/{report['id']}/pdf", headers=h)
    text_content = "".join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert DISCLAIMER in text_content and "科研样例" in text_content
    output = ROOT / ".runtime" / "report-sample.pdf"
    output.parent.mkdir(exist_ok=True)
    output.write_bytes(pdf.content)
    with engine.connect() as connection:
        with pytest.raises(DatabaseError):
            connection.execute(text("UPDATE report SET content='{}' WHERE id=:id"), {"id": report["id"]})
        connection.rollback()
    overview = client.get("/api/v1/stats/overview", headers=h).json()["data"]
    assert overview["reports_signed"] == 1 and overview["images"] == 21
    # Template edits do not change the previously rendered signed report.
    client.patch(
        f"/api/v1/report-templates/{template['id']}",
        headers=h,
        json={"body": "<p>新版模板</p><p>{{ disclaimer }}</p>"},
    )
    assert client.get(f"/api/v1/reports/{report['id']}/pdf", headers=h).content == pdf.content


def test_template_sandbox(client, headers):
    for body in (
        "<p>no disclaimer</p>",
        "<script>alert(1)</script>{{ disclaimer }}",
        "{{ ''.__class__ }}{{ disclaimer }}",
        "{% for x in range(1000000) %}x{% endfor %}{{ disclaimer }}",
    ):
        response = client.post(
            "/api/v1/report-templates",
            headers=headers["admin"],
            json={"name": "bad", "body": body, "variables": []},
        )
        assert response.status_code == 422, response.text


def test_worker_failure_is_persisted(client, headers, imported, monkeypatch):
    from app import worker

    with SessionLocal() as db:
        user = db.scalar(select(m.User).where(m.User.username == "admin"))
        model = m.Model(name="transunet")
        db.add(model)
        db.flush()
        config = json.loads((ROOT / "algo/models/registry.json").read_text())["models"][0]["config"]
        version = m.ModelVersion(
            model_id=model.id,
            version="broken",
            weights_key="missing.pth",
            weights_sha256="0" * 64,
            config=config,
            created_by=user.id,
            status="active",
        )
        db.add(version)
        db.commit()

    def fail(*args):
        raise RuntimeError("secret-internal-detail")

    monkeypatch.setattr(worker, "run_prediction", fail)
    task = post(client, "/inference-tasks", headers["admin"], {"image_id": imported[1][0]["id"]}, 202)
    drain_eager()
    result = client.get("/api/v1/inference-tasks/" + task["task_id"], headers=headers["admin"])
    assert result.json()["data"]["status"] == "failed"
    assert "secret-internal-detail" not in result.text


@pytest.mark.parametrize(
    "role,allowed",
    [
        (
            "admin",
            {
                "users",
                "datasets",
                "images",
                "annotation-tasks",
                "screen-tasks",
                "audit-logs",
                "stats/overview",
            },
        ),
        ("data_engineer", {"datasets", "images", "annotation-tasks", "stats/overview"}),
        ("annotator", {"images", "annotation-tasks", "stats/overview"}),
        ("screener", {"images", "screen-tasks", "stats/overview"}),
        ("reviewer", {"images", "annotation-tasks", "stats/overview"}),
    ],
)
def test_five_role_read_matrix(client, headers, role, allowed):
    for path in (
        "users",
        "datasets",
        "images",
        "annotation-tasks",
        "screen-tasks",
        "audit-logs",
        "stats/overview",
    ):
        assert client.get("/api/v1/" + path, headers=headers[role]).status_code == (
            200 if path in allowed else 403
        )


def test_claim_race_only_one_winner(client, headers, imported):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from app.common import APIError
    from app.routes_annotations import claim

    task_id = post(client, "/annotation-tasks", headers["admin"], {"image_ids": [imported[1][0]["id"]]}, 201)[
        "task_ids"
    ][0]
    barrier = Barrier(2)

    def attempt(username):
        with SessionLocal() as db:
            user = db.scalar(select(m.User).where(m.User.username == username))
            barrier.wait(timeout=10)
            try:
                claim(db, m.AnnotationTask, task_id, user)
                db.commit()
                return "claimed"
            except APIError as exc:
                db.rollback()
                return exc.status

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(attempt, ["admin", "annotator"]))
    assert outcomes.count("claimed") == 1 and outcomes.count(409) == 1


def test_rle_validation_and_signed_url_token_separation(client, headers, imported):
    image = imported[1][0]
    h = headers["annotator"]
    for rle in (
        {"size": [12, 16], "counts": "compressed"},
        {"size": [-1, 2], "counts": [2]},
        {"size": [12, 16], "counts": [1]},
        {"size": [12, 16], "counts": [True, 191]},
    ):
        assert (
            client.post(
                "/api/v1/annotations",
                headers=h,
                json={"image_id": image["id"], "source": "manual", "mask_rle": rle},
            ).status_code
            == 422
        )
    signed = (
        client.get(f"/api/v1/images/{image['id']}/file", headers=h, follow_redirects=False)
        .headers["location"]
        .rsplit("/", 1)[1]
    )
    assert client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + signed}).status_code == 401


def test_duplicate_class_conflict_is_visible(client, headers):
    import numpy as np
    from conftest import png_bytes

    dataset = post(client, "/datasets", headers["admin"], {"name": "duplicates"}, 201)
    image = png_bytes(np.arange(192).reshape(12, 16))
    mask = png_bytes(np.ones((12, 16)) * 255)
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        for label in ("benign", "malignant"):
            z.writestr(f"{label}/{label} (1).png", image)
            z.writestr(f"{label}/{label} (1)_mask.png", mask)
    response = client.post(
        f"/api/v1/datasets/{dataset['id']}/imports",
        headers=headers["admin"],
        files={"file": ("test.zip", archive.getvalue(), "application/zip")},
    )
    assert response.status_code == 202
    drain_eager()
    job = client.get("/api/v1/imports/" + response.json()["data"]["job_id"], headers=headers["admin"]).json()[
        "data"
    ]
    assert job["success"] == 1 and job["duplicate"] == 1
    assert job["report"]["warnings"][0]["class_conflict"] is True


def test_study_review_modify_creates_annotation_without_hijacking_task(client, headers, imported):
    _, images = imported
    image = images[0]
    annotation_task = post(client, "/annotation-tasks", headers["admin"], {"image_ids": [image["id"]]}, 201)[
        "task_ids"
    ][0]
    post(client, f"/annotation-tasks/{annotation_task}/claim", headers["annotator"])
    patient = post(client, "/patients", headers["screener"], {"gender": "F"}, 201)
    study = post(
        client,
        "/studies",
        headers["screener"],
        {"patient_id": patient["id"], "study_date": "2026-11-02", "image_ids": [image["id"]]},
        201,
    )
    task = post(client, "/screen-tasks", headers["screener"], {"study_id": study["id"]}, 201)
    post(client, f"/screen-tasks/{task['id']}/claim", headers["screener"])
    payload = {
        "decision": "modify",
        "image_id": image["id"],
        "mask_rle": {"size": [12, 16], "counts": [0, 192]},
        "is_empty": False,
        "comment": "医生修正边界",
    }
    review = post(client, f"/studies/{study['id']}/reviews", headers["screener"], payload)
    assert review["decision"] == "modify"
    history = client.get(f"/api/v1/images/{image['id']}/annotations", headers=headers["screener"]).json()[
        "data"
    ]
    assert history[0]["version"] == 2
    assert history[0]["status"] == "draft" and history[0]["source"] == "manual"
    with SessionLocal() as db:
        row = db.get(m.AnnotationTask, annotation_task)
        assert row.status == "in_progress" and row.annotation_id is None and row.assignee_id
    assert (
        client.post(
            f"/api/v1/studies/{study['id']}/reviews", headers=headers["screener"], json=payload
        ).status_code
        == 409
    )


def test_studies_search_exclusion_version_filter_and_reports_list(client, headers, imported):
    dataset_id, images = imported
    image = images[0]
    patient = post(client, "/patients", headers["screener"], {"gender": "F"}, 201)
    study = post(
        client,
        "/studies",
        headers["screener"],
        {"patient_id": patient["id"], "study_date": "2026-11-02", "image_ids": [image["id"]]},
        201,
    )
    listed = client.get("/api/v1/studies?q=" + study["study_no"], headers=headers["reviewer"]).json()
    assert listed["meta"]["total"] == 1
    row = listed["data"][0]
    assert row["patient_no"] == patient["patient_no"] and row["image_count"] == 1
    assert row["screen_task"] is None and row["report"] is None

    assert (
        client.post(
            f"/api/v1/images/{image['id']}/exclude",
            headers=headers["annotator"],
            json={"exclude_reason": "blur"},
        ).status_code
        == 403
    )
    excluded = post(
        client, f"/images/{image['id']}/exclude", headers["data_engineer"], {"exclude_reason": "模糊"}
    )
    assert excluded["excluded"] is True
    assert client.get("/api/v1/images?exclude=true", headers=headers["admin"]).json()["meta"]["total"] == 1
    version = post(
        client,
        "/dataset-versions",
        headers["data_engineer"],
        {"dataset_id": dataset_id, "version": "usable", "filter": {"only_usable": True}},
        201,
    )
    frozen = post(client, f"/dataset-versions/{version['id']}/freeze", headers["data_engineer"])
    assert sum(frozen["counts"].values()) == 20
    restored = post(
        client, f"/images/{image['id']}/exclude", headers["data_engineer"], {"exclude_reason": None}
    )
    assert restored["excluded"] is False

    assert client.get("/api/v1/reports", headers=headers["admin"]).json()["data"] == []
    assert client.get("/api/v1/reports", headers=headers["annotator"]).status_code == 403
    preview = post(
        client,
        "/report-templates/preview",
        headers["admin"],
        {"body": "<p>{{ patient_no }}</p><p>{{ disclaimer }}</p>", "variables": ["patient_no"]},
        200,
    )
    assert "P0001" in preview["html"] and "仅供科研" in preview["html"]
    assert (
        client.post(
            "/api/v1/report-templates/preview",
            headers=headers["screener"],
            json={"body": "<p>{{ disclaimer }}</p>", "variables": []},
        ).status_code
        == 403
    )


def test_dual_annotation_consistency_and_arbitration(client, headers, imported):
    _, images = imported
    full = {"size": [12, 16], "counts": [0, 192]}
    empty = {"size": [12, 16], "counts": [192]}
    for index in (0, 1):
        image = images[index]
        task_id = post(
            client,
            "/annotation-tasks",
            headers["admin"],
            {"image_ids": [image["id"]], "required_annotators": 2},
            201,
        )["task_ids"][0]
        post(client, f"/annotation-tasks/{task_id}/claim", headers["annotator"])
        joined = post(client, f"/annotation-tasks/{task_id}/join", headers["admin"])
        assert joined["required_annotators"] == 2 and len(joined["participants"]) == 2
        assert (
            client.post(f"/api/v1/annotation-tasks/{task_id}/join", headers=headers["annotator"]).status_code
            == 409
        )
        first = post(
            client,
            "/annotations",
            headers["annotator"],
            {"image_id": image["id"], "mask_rle": full, "source": "manual"},
            201,
        )
        post(client, f"/annotations/{first['id']}/submit", headers["annotator"])
        mask = full if index == 0 else empty
        second = post(
            client,
            "/annotations",
            headers["admin"],
            {"image_id": image["id"], "mask_rle": mask, "source": "manual", "is_empty": index == 1},
            201,
        )
        second = post(client, f"/annotations/{second['id']}/submit", headers["admin"])

    tasks = client.get("/api/v1/annotation-tasks?page_size=10", headers=headers["admin"]).json()["data"]
    by_image = {item["image_id"]: item for item in tasks}
    auto, dispute = by_image[images[0]["id"]], by_image[images[1]["id"]]
    assert auto["status"] == "approved" and auto["consistency"]["auto"] is True
    assert auto["consistency"]["iou"] == 1.0
    assert dispute["status"] == "submitted" and dispute["consistency"]["auto"] is False
    assert dispute["consistency"]["iou"] == 0.0
    pending = client.get(
        f"/api/v1/images/{images[1]['id']}/annotations?status=pending", headers=headers["reviewer"]
    ).json()["data"]
    assert len(pending) == 2
    chosen = pending[0]
    approved = post(
        client,
        f"/annotations/{chosen['id']}/reviews",
        headers["reviewer"],
        {"decision": "approve", "comment": "仲裁通过"},
    )
    assert approved["status"] == "approved"
    others = client.get(f"/api/v1/images/{images[1]['id']}/annotations", headers=headers["reviewer"]).json()[
        "data"
    ]
    assert sum(item["status"] == "approved" for item in others) == 1
    assert sum(item["status"] == "rejected" for item in others) == 2


def test_report_ai_draft_prefill(client, headers, imported, monkeypatch):
    import numpy as np
    from app import worker
    from conftest import png_bytes

    _, images = imported
    image = images[0]
    registry = json.loads((ROOT / "algo/models/registry.json").read_text())["models"][0]
    model = post(client, "/models", headers["admin"], {"name": "transunet"}, 201)
    storage.put("bidlsp-model", "draft/weights.pth", b"draft-weight")
    import hashlib

    version = post(
        client,
        f"/models/{model['id']}/versions",
        headers["admin"],
        {
            "version": "draft",
            "weights_key": "draft/weights.pth",
            "weights_sha256": hashlib.sha256(b"draft-weight").hexdigest(),
            "config": registry["config"],
            "metrics": registry["metrics"],
        },
        201,
    )
    post(client, f"/model-versions/{version['id']}/activate", headers["admin"])

    def fake_prediction(db, task):
        path = settings.work_dir / task.id / "mask.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes(np.ones((12, 16), dtype="uint8") * 255))
        return {
            "result": {
                "mask_rle": {"size": [12, 16], "counts": [0, 192]},
                "prob_mean": 0.7,
                "lesion_area_ratio": 0.25,
                "quality_flags": ["AREA_TOO_LARGE"],
                "elapsed_ms": 10,
            },
            "artifacts": {"mask": str(path), "mask_raw": str(path), "overlay": str(path)},
        }

    monkeypatch.setattr(worker, "run_prediction", fake_prediction)
    patient = post(client, "/patients", headers["screener"], {"gender": "F"}, 201)
    study = post(
        client,
        "/studies",
        headers["screener"],
        {"patient_id": patient["id"], "study_date": "2026-11-02", "image_ids": [image["id"]]},
        201,
    )
    task = post(client, "/screen-tasks", headers["screener"], {"study_id": study["id"]}, 201)
    post(client, f"/screen-tasks/{task['id']}/claim", headers["screener"])
    post(client, "/inference-tasks", headers["screener"], {"image_id": image["id"]}, 202)
    drain_eager()
    post(client, f"/studies/{study['id']}/reviews", headers["screener"], {"decision": "accept"})
    template = client.get("/api/v1/report-templates", headers=headers["admin"]).json()["data"][0]
    report = post(
        client,
        "/reports",
        headers["screener"],
        {
            "study_id": study["id"],
            "inference_result_id": None,
            "template_id": template["id"],
            "content": {"findings": "", "impression": "", "recommendation": ""},
        },
        201,
    )
    assert report["content"]["findings"].startswith("[AI 草稿")
    assert "面积占比" in report["content"]["findings"]
    pdf = client.get(f"/api/v1/reports/{report['id']}/pdf", headers=headers["admin"])
    assert "AI 草稿" in "".join(page.extract_text() for page in PdfReader(io.BytesIO(pdf.content)).pages)
    listed = client.get("/api/v1/reports?status=draft", headers=headers["admin"]).json()
    assert listed["meta"]["total"] == 1 and listed["data"][0]["id"] == report["id"]


def test_task_release_reassign_archive_and_evaluation_list(client, headers, imported):
    dataset_id, images = imported
    version = post(
        client,
        "/dataset-versions",
        headers["data_engineer"],
        {"dataset_id": dataset_id, "version": "v-archive"},
        201,
    )
    assert (
        client.post(
            f"/api/v1/dataset-versions/{version['id']}/archive", headers=headers["data_engineer"]
        ).status_code
        == 409
    )
    post(client, f"/dataset-versions/{version['id']}/freeze", headers["data_engineer"])
    assert (
        client.get(
            f"/api/v1/dataset-versions/{version['id']}/manifest",
            headers=headers["admin"],
            follow_redirects=False,
        ).status_code
        == 302
    )
    archived = post(client, f"/dataset-versions/{version['id']}/archive", headers["data_engineer"])
    assert archived["status"] == "archived"
    assert (
        client.post(
            f"/api/v1/dataset-versions/{version['id']}/archive", headers=headers["data_engineer"]
        ).status_code
        == 409
    )

    task = post(client, "/annotation-tasks", headers["admin"], {"image_ids": [images[0]["id"]]}, 201)[
        "task_ids"
    ][0]
    post(client, f"/annotation-tasks/{task}/claim", headers["annotator"])
    assert (
        client.post(f"/api/v1/annotation-tasks/{task}/release", headers=headers["admin"]).status_code == 409
    )
    released = post(client, f"/annotation-tasks/{task}/release", headers["annotator"])
    assert released["status"] == "pending" and released["assignee_id"] is None
    assert (
        client.post(f"/api/v1/annotation-tasks/{task}/release", headers=headers["annotator"]).status_code
        == 409
    )
    reclaim = post(client, f"/annotation-tasks/{task}/claim", headers["annotator"])
    assert reclaim["status"] == "in_progress" and reclaim["assignee_id"]

    users = client.get("/api/v1/users?page_size=100", headers=headers["admin"]).json()["data"]
    reviewer_id = next(u["id"] for u in users if u["username"] == "reviewer")
    patient = post(client, "/patients", headers["screener"], {"gender": "F"}, 201)
    study = post(
        client,
        "/studies",
        headers["screener"],
        {"patient_id": patient["id"], "study_date": "2026-11-02", "image_ids": [images[1]["id"]]},
        201,
    )
    screen = post(client, "/screen-tasks", headers["screener"], {"study_id": study["id"]}, 201)
    post(client, f"/screen-tasks/{screen['id']}/claim", headers["screener"])
    assert (
        client.post(
            f"/api/v1/screen-tasks/{screen['id']}/reassign",
            headers=headers["screener"],
            json={"assignee_id": reviewer_id},
        ).status_code
        == 403
    )
    assert (
        client.post(
            f"/api/v1/screen-tasks/{screen['id']}/reassign",
            headers=headers["admin"],
            json={"assignee_id": next(u["id"] for u in users if u["username"] == "annotator")},
        ).status_code
        == 422
    )
    admin_id = next(u["id"] for u in users if u["username"] == "admin")
    assert (
        client.post(
            f"/api/v1/screen-tasks/{screen['id']}/reassign",
            headers=headers["admin"],
            json={"assignee_id": reviewer_id},
        ).status_code
        == 422
    )
    moved = post(
        client, f"/screen-tasks/{screen['id']}/reassign", headers["admin"], {"assignee_id": admin_id}
    )
    assert moved["assignee"]["id"] == admin_id and moved["status"] == "in_progress"
    assert (
        client.post(f"/api/v1/screen-tasks/{screen['id']}/release", headers=headers["admin"]).json()["data"][
            "status"
        ]
        == "pending"
    )
    assert (
        client.post(f"/api/v1/screen-tasks/{screen['id']}/release", headers=headers["admin"]).status_code
        == 409
    )

    assert client.get("/api/v1/evaluations", headers=headers["admin"]).json()["data"] == []
    assert client.get("/api/v1/evaluations", headers=headers["screener"]).status_code == 403


def register_version(client, headers, version="mv-test"):
    import hashlib

    registry = json.loads((ROOT / "algo/models/registry.json").read_text())["models"][0]
    model = post(client, "/models", headers["admin"], {"name": "transunet"}, 201)
    storage.put("bidlsp-model", f"test/{version}.pth", b"test-weight")
    return post(
        client,
        f"/models/{model['id']}/versions",
        headers["admin"],
        {
            "version": version,
            "weights_key": f"test/{version}.pth",
            "weights_sha256": hashlib.sha256(b"test-weight").hexdigest(),
            "config": registry["config"],
            "metrics": registry["metrics"],
        },
        201,
    )


def test_activation_requires_platform_evaluation(client, headers, monkeypatch):
    from types import SimpleNamespace

    from app import worker

    h = headers["admin"]
    version = register_version(client, headers)
    monkeypatch.setattr(settings, "allow_unverified_model", False)
    blocked = client.post(f"/api/v1/model-versions/{version['id']}/activate", headers=h)
    assert blocked.status_code == 409 and blocked.json()["code"] == "MODEL_NOT_VERIFIED"

    # 评估成功即回写指标与回归结论，激活门禁随之放行。
    with SessionLocal() as db:
        worker.apply_evaluation(
            db,
            SimpleNamespace(id="eval-1", model_version_id=version["id"]),
            {"A2+A1": {"dice": 0.7240}, "A2+A1+A3": {"dice": 0.7087}},
            {"result": "PASS", "comparable_split": True},
        )
        db.commit()
    activated = post(client, f"/model-versions/{version['id']}/activate", h)
    assert activated["status"] == "active" and "warning" not in activated
    detail = client.get(f"/api/v1/model-versions/{version['id']}", headers=h).json()["data"]
    assert detail["metrics_source"] == "platform_eval" and detail["evaluation_job_id"] == "eval-1"

    # 回归 FAIL 即使开放放行也必须拦截。
    with SessionLocal() as db:
        db.get(m.ModelVersion, version["id"]).regression = {"result": "FAIL"}
        db.commit()
    monkeypatch.setattr(settings, "allow_unverified_model", True)
    assert client.post(f"/api/v1/model-versions/{version['id']}/activate", headers=h).status_code == 409


def test_batch_retry_reissues_only_failed_subtasks(client, headers, imported, monkeypatch):
    import numpy as np
    from app import worker
    from conftest import png_bytes

    dataset_id, images = imported
    h = headers["admin"]
    dataset_version = post(
        client, "/dataset-versions", h, {"dataset_id": dataset_id, "version": "v-batch"}, 201
    )
    post(client, f"/dataset-versions/{dataset_version['id']}/freeze", h)
    version = register_version(client, headers)
    post(client, f"/model-versions/{version['id']}/activate", h)
    batch = post(
        client,
        "/inference-batches",
        h,
        {"dataset_version_id": dataset_version["id"], "model_version_id": version["id"]},
        202,
    )

    with SessionLocal() as db:
        failed = list(
            db.scalars(select(m.InferenceTask).where(m.InferenceTask.batch_id == batch["batch_id"]).limit(3))
        )
        failed_ids = [task.id for task in failed]
        for task in failed:
            task.status, task.error = "failed", {"code": "INFERENCE_FAILED"}
        db.commit()

    detail = client.get(f"/api/v1/inference-batches/{batch['batch_id']}", headers=h).json()["data"]
    assert detail["failed"] == 3 and detail["total"] == len(images) and detail["succeeded"] == 0

    retried = post(client, f"/inference-batches/{batch['batch_id']}/retry", h)
    assert retried["retried"] == 3 and retried["in_flight"] == len(images) - 3
    # 重投后旧失败尝试不计入进度，重复点击不会二次提交在途任务。
    again = post(client, f"/inference-batches/{batch['batch_id']}/retry", h)
    assert again["retried"] == 0 and again["in_flight"] == len(images)
    with SessionLocal() as db:
        attempts = list(db.scalars(select(m.InferenceTask).where(m.InferenceTask.id.in_(failed_ids))))
        assert all(task.attempt == 1 and task.status == "failed" for task in attempts)
        assert (
            db.scalar(
                select(m.InferenceTask)
                .where(m.InferenceTask.batch_id == batch["batch_id"], m.InferenceTask.attempt == 2)
                .limit(1)
            )
            is not None
        )

    def fake_prediction(db, task):
        path = settings.work_dir / task.id / "mask.png"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(png_bytes(np.ones((12, 16), dtype="uint8") * 255))
        return {
            "result": {
                "mask_rle": {"size": [12, 16], "counts": [0, 192]},
                "prob_mean": 0.8,
                "lesion_area_ratio": 1.0,
                "quality_flags": ["AREA_TOO_LARGE"],
                "elapsed_ms": 20,
            },
            "artifacts": {"mask": str(path), "mask_raw": str(path), "overlay": str(path)},
        }

    monkeypatch.setattr(worker, "run_prediction", fake_prediction)
    drain_eager()
    final = client.get(f"/api/v1/inference-batches/{batch['batch_id']}", headers=h).json()["data"]
    assert final["status"] == "succeeded" and final["succeeded"] == len(images) and final["failed"] == 0
