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


def test_openapi_matches_all_64_contract_endpoints():
    contract = (ROOT / "接口规范.md").read_text(encoding="utf-8")
    expected = re.findall(r"\| \d{3} \| (GET|POST|PATCH) \| `([^`]+)`", contract)
    actual = app.openapi()["paths"]
    assert len(expected) == 64
    for method, path in expected:
        assert method.lower() in actual["/api/v1" + path], path
    assert (
        len([(p, v) for p, methods in actual.items() for v in methods if v in {"get", "post", "patch"}]) == 64
    )


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
